#!/usr/bin/env python3
r"""Local JEV bridge for jev-browser (jkudish/jev-browser), backed by parallel-decisions.

WHY
    @jkudish/jev-browser sends every browser-step judgment to TypeSafe's hosted
    "system one" API and, optionally, its typed text to a cloud LLM. This server
    replaces both with local inference:

      POST /v1/systemone         -> parallel-decisions (Qwen2.5-0.5B, CUDA by default)
      POST /v1/chat/completions  -> the same cached model used as a tiny text helper
      GET  /health

    jev-browser is pointed here with:
      TYPESAFE_BASE_URL=http://127.0.0.1:8768
      TYPESAFE_API_KEY=local-jev          (dummy; the SDK insists on a non-empty key)
      JEV_BROWSER_TYPE_BASE_URL=http://127.0.0.1:8768/v1
      JEV_BROWSER_TYPE_MODEL=qwen2.5-0.5b-local

    Nothing here contacts the network. The only outbound traffic is the browser
    jev-browser itself drives.

PROTOCOL NOTES
    systemone request:  {model?, state, questions}
      questions: {name: {type: "choice"|"noul"|"score", instructions, criteria}}
        choice.criteria -> {label: description}   (mapped to an engine enum field)
        noul.criteria   -> {true: ..., false: ...} (mapped to an engine boolean field)
    systemone response: {answers: {name: answer}, usage: {input_tokens, output_tokens}}
        choice answer -> {type: "choice", choice: <label>, probabilities: {...}, confidence: p}
        noul   answer -> {type: "noul", noul: P(true)}

    "confidence" here is the engine's raw softmax probability of the chosen label --
    a proxy, not a trained calibration. The bridge reports it honestly and does not
    pretend to be TypeSafe's calibrated confidence.

Run with the *gpu* venv that has torch+cu124 and the parallel-decisions checkout
(see README.md "Running"):
    & ..\parallel-decisions_wt\gpu\.venv\Scripts\python.exe local_jev_server.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MAX_BODY_BYTES = 4_000_000  # one jev-browser state can carry dozens of KB
SERVER_VERSION = "local-jev-server/0.1"

# Latency guards. Prefill on this class of GPU grows ~quadratically with prompt
# length (eager attention), so a 240-element page can take minutes. The bridge
# ranks element candidates against the task and keeps only the best few.
MAX_CHOICES = 40      # element actions kept per step (controls are always kept)
DESC_CHARS = 64       # per-option description budget
LOGGING = True
GOAL_TITLE_MATCH = True  # code-owned stop signal (see _goal_title_match)

DECIDER = None              # parallel_decisions.Decider
TYPING = None               # _TypingModel | None
TYPING_LOCK = threading.Lock()
STATS = {"systemone": 0, "typing": 0, "errors": 0}
STATS_LOCK = threading.Lock()

ELEMENT_RE = re.compile(r"^(click|type|select)_e\d+$")
_SEARCH_URL_RE = re.compile(r"[?&](q|query|search|p)=|/search|special:search|search\?", re.IGNORECASE)
_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by",
    "is", "are", "was", "be", "it", "this", "that", "you", "your", "stop", "when",
    "task", "page", "find", "open", "go", "search", "click", "type", "select",
}


def _log(message: str) -> None:
    if LOGGING:
        print(f"[local-jev] {message}", file=sys.stderr, flush=True)


# --- VRAM headroom guard --------------------------------------------------- #
# On an 8 GB card with a desktop running, loading a 1.5B decision model plus a
# 0.5B typing model leaves almost no headroom. Windows then pages GPU memory to
# shared system RAM and decision latency degrades 10-20x (measured: 0.6-0.9 s ->
# 10-14 s). The guard refuses an impossible load and skips the optional typing
# model when the card is tight; `--force-vram` / `--typing` override both.

VRAM_HEADROOM_GB = 1.5


def _free_vram_gb() -> float | None:
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        free, _total = torch.cuda.mem_get_info()
        return free / (1024 ** 3)
    except Exception:
        return None


def _estimate_model_gb(model_id: str, dtype_bytes: int = 2) -> float:
    """Rough parameter-count estimate for full-attention decoder models."""
    try:
        from transformers import AutoConfig
        cfg = AutoConfig.from_pretrained(model_id)
        hidden = int(getattr(cfg, "hidden_size", 0) or 0)
        layers = int(getattr(cfg, "num_hidden_layers", 0) or 0)
        vocab = int(getattr(cfg, "vocab_size", 0) or 0)
        if not (hidden and layers and vocab):
            return 4.0
        inter = int(getattr(cfg, "intermediate_size", hidden * 4) or hidden * 4)
        heads = int(getattr(cfg, "num_attention_heads", 1) or 1)
        kv_heads = int(getattr(cfg, "num_key_value_heads", heads) or heads)
        head_dim = int(getattr(cfg, "head_dim", max(1, hidden // heads)) or max(1, hidden // heads))
        attn = hidden * heads * head_dim + 2 * hidden * kv_heads * head_dim + heads * head_dim * hidden
        mlp = 3 * hidden * inter
        params = 2 * vocab * hidden + layers * (attn + mlp)  # embed + lm_head + blocks
        return params * dtype_bytes / (1024 ** 3)
    except Exception:
        return 4.0


def _token_set(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if len(w) > 1 and w not in _STOPWORDS}


_NOISY_CLICK_RE = re.compile(r"menu|toggle|theme|sidebar|skip to|language", re.IGNORECASE)


def _prune_criteria(criteria: dict[str, str], task_text: str, max_keep: int, desc_chars: int) -> tuple[dict[str, str], int, int]:
    """Keep the most task-relevant element actions, best match first; controls last.

    Returns (criteria, kept_elements, total_elements). Ranking is a deterministic
    keyword-overlap heuristic on the option descriptions -- good enough to surface
    the search box, the named link, or the form field a task mentions, while
    keeping the prompt inside the engine's fast prefill range. Ordering matters
    for small models: they show a strong bias toward the first options offered.
    """
    labels = list(criteria.keys())
    controls = [(label, str(criteria[label])) for label in labels if not ELEMENT_RE.match(label)]
    candidates: list[tuple[str, str, str, int]] = []
    for index, label in enumerate(labels):
        if not ELEMENT_RE.match(label):
            continue
        description = str(criteria[label])
        kind = label.split("_", 1)[0]
        if kind == "click" and _NOISY_CLICK_RE.search(description):
            continue  # main menus, theme toggles, language pickers, ...
        candidates.append((label, description, kind, index))

    task_tokens = _token_set(task_text)

    # IDF-style weighting: a match on a rare task word ("ristretto") is worth much
    # more than a match on a word that appears in dozens of link descriptions
    # ("wikipedia", "article"), which is what generic ranking kept confusing.
    tokens_per_candidate = [_token_set(description) for _l, description, _k, _i in candidates]
    document_frequency: dict[str, int] = {}
    for tokens in tokens_per_candidate:
        for token in tokens:
            document_frequency[token] = document_frequency.get(token, 0) + 1

    def score(index: int) -> float:
        tokens = tokens_per_candidate[index]
        return sum(1.0 + 1.0 / document_frequency.get(token, 1) for token in tokens & task_tokens)

    scored = [
        (item, score(index))
        for index, item in enumerate(candidates)
    ]
    ranked = sorted(scored, key=lambda pair: (-pair[1], pair[0][3]))
    total = len(candidates)
    if total > max_keep:
        kept = ranked[:max_keep]
        if not any(item[2] in ("type", "select") for item, _s in kept):
            best_input = next(((item, s) for item, s in ranked if item[2] in ("type", "select")), None)
            if best_input is not None:
                kept = kept[:-1] + [best_input]
        ranked = sorted(kept, key=lambda pair: (-pair[1], pair[0][3]))

    pruned: dict[str, str] = {
        item[0]: item[1][:desc_chars] for item, _s in ranked
    }
    for label, description in controls:
        pruned[label] = description[:desc_chars]
    return pruned, len(ranked), total


def _focus_tokens(task: str) -> list[str]:
    """Distinctive words from the task: quoted strings and proper nouns.

    "Search Wikipedia for the espresso-based drink called Ristretto" -> ["Ristretto"].
    """
    quoted = re.findall(r'"([^"]{2,80})"', task)
    proper = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z'\-]{2,}", task)
        if word[0].isupper() and word.lower() not in _QUERY_STOP
    ]
    out: list[str] = []
    for word in quoted + proper:
        if word.lower() not in {existing.lower() for existing in out}:
            out.append(word)
    return out


def _goal_title_match(state: Any) -> str | None:
    """Return the task token found in the current page title/URL, if any."""
    if not isinstance(state, dict):
        return None
    task = str(state.get("task", ""))
    page = state.get("current_page") or {}
    haystack = f"{page.get('title', '')} {page.get('url', '')}".lower()
    for token in _focus_tokens(task):
        if token.lower() in haystack:
            return token
    return None


# --- typing-adapter guard -------------------------------------------------- #
# A 0.5B instruction model tends to echo the field label ("Search Wikipedia")
# instead of the text the task implies. The adapter strips label echoes and,
# when the result is still label-like or empty, derives the value from the
# task keywords. This is the local stand-in for "a small model writes text".

_TASK_RE = re.compile(r'performing this task:\s*"([^"]{3,600})"', re.IGNORECASE)
_FIELD_RE = re.compile(r"type into the (.{0,200}?) on https?://", re.IGNORECASE)
_QUOTED_RE = re.compile(r'"([^"]{1,120})"')
_QUERY_STOP = _STOPWORDS | {
    "wikipedia", "search", "find", "open", "article", "called", "into", "from",
    "website", "site", "page", "link", "click", "type", "select", "stop", "when",
    "you", "are", "that", "this", "with", "about", "visit", "browse",
}


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _typing_fallback(text: str, messages: list[Any]) -> str:
    user_text = ""
    for message in reversed(messages):
        if isinstance(message, dict) and message.get("role") == "user":
            user_text = _message_text(message)
            break
    if not user_text:
        return text

    field_match = _FIELD_RE.search(user_text)
    field = field_match.group(1).strip() if field_match else ""
    label = ""
    if field:
        quoted = _QUOTED_RE.search(field)
        if quoted:
            label = quoted.group(1).strip()

    cleaned = text
    for candidate in (label, field):
        if candidate and cleaned.lower().startswith(candidate.lower()):
            cleaned = cleaned[len(candidate):].strip(" -:,\"'")

    label_like = bool(field) and (not cleaned or cleaned.lower() in field.lower() or len(cleaned) < 3)
    if cleaned and not label_like:
        return cleaned

    task_match = _TASK_RE.search(user_text)
    if not task_match:
        return cleaned or text
    task = task_match.group(1)

    # The shortest query is usually the best one: a quoted string if the task has
    # one, otherwise the proper nouns ("Search Wikipedia for the espresso-based
    # drink called Ristretto" -> "Ristretto"). The all-keywords query buried the
    # target article on page 0 of Wikipedia results, so for search boxes the
    # specific term wins over the keyword soup.
    quoted = re.findall(r'"([^"]{2,80})"', task)
    proper = [
        word
        for word in re.findall(r"[A-Za-z][A-Za-z'\-]*", task)
        if word[0].isupper() and len(word) > 1 and word.lower() not in _QUERY_STOP
    ]
    specific = quoted[0] if quoted else (" ".join(proper[:2]) if proper else "")

    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", task)
    keep = [word for word in words if len(word) > 1 and word.lower() not in _QUERY_STOP]
    keyword_query = " ".join(keep[:6]).strip()

    if re.search(r"search", field, re.IGNORECASE) and specific:
        return specific
    if cleaned and not label_like:
        return cleaned
    return specific or keyword_query or cleaned or text



def _bump(key: str, n: int = 1) -> None:
    with STATS_LOCK:
        STATS[key] = STATS.get(key, 0) + n


# --------------------------------------------------------------------------- #
# State / question translation
# --------------------------------------------------------------------------- #

def _text(value: Any) -> str:
    """Flatten an SDK `instructions` field (string | object | array | null)."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return json.dumps(value, ensure_ascii=False)


def _render_state(state: Any) -> str:
    """Turn jev-browser's JSON state into readable context text for the engine.

    The action criteria (element list) travel inside the question, so the context
    only needs what the model cannot see there: task, page identity, visible text
    excerpt and action history.
    """
    if isinstance(state, str):
        return state
    if not isinstance(state, dict):
        return json.dumps(state, ensure_ascii=False)

    lines: list[str] = []
    task = state.get("task")
    if task:
        lines.append(f"TASK: {task}")

    page = state.get("current_page") or {}
    if page.get("url") or page.get("title"):
        lines.append(f"PAGE: {page.get('title', '')} ({page.get('url', '')})")

    excerpt = state.get("page_text_excerpt")
    if excerpt:
        lines.append(f"PAGE TEXT: {excerpt}")

    history = state.get("history") or []
    if history:
        # Outcomes only: never echo action IDs back at the model. The engine's
        # decision suffix starts with `"action": "` and option IDs like click_e2
        # in the context act as a recency prior -- observed as a self-reinforcing
        # loop where the model re-picks the same option on every page.
        outcomes = [str(item.get("outcome", "")) for item in history[-8:]]
        outcomes = [outcome for outcome in outcomes if outcome]
        if outcomes:
            lines.append("HISTORY: " + "; ".join(outcomes))

    if state.get("element_list_truncated"):
        lines.append("NOTE: the element list was truncated; more controls exist below.")

    # Anything unexpected still reaches the model instead of being dropped.
    known = {"task", "current_page", "page_text_excerpt", "history", "element_list_truncated",
             "no_interactive_elements", "interactive_elements"}
    rest = {k: v for k, v in state.items() if k not in known and v not in (None, [], {}, "")}
    if rest:
        lines.append("EXTRA: " + json.dumps(rest, ensure_ascii=False))

    return "\n".join(lines)


def _questions_to_schema(questions: dict[str, Any], state: Any) -> tuple[Any, dict[str, str], dict[str, Any]]:
    """Map TypeSafe question shapes onto parallel-decisions Schema fields.

    Returns (Schema, {name: kind}, info) where kind is "choice" | "noul" and info
    carries pruning stats for logging.
    Choice criteria maps have the exact {label: description} form the engine's
    enum fields already accept; noul criteria maps are {true: ..., false: ...}.
    """
    from parallel_decisions import Schema

    fields: dict[str, dict[str, Any]] = {}
    kinds: dict[str, str] = {}
    info: dict[str, Any] = {}
    task_text = str((state or {}).get("task", "")) if isinstance(state, dict) else str(state or "")

    for name, question in questions.items():
        if not isinstance(question, dict):
            raise ValueError(f"question {name!r} is not an object")
        qtype = str(question.get("type", "")).lower()
        instructions = _text(question.get("instructions"))
        criteria = question.get("criteria")

        if qtype == "choice":
            if not isinstance(criteria, dict) or len(criteria) < 2:
                raise ValueError(f"choice question {name!r} needs at least 2 criteria")
            raw = {str(k): str(v) for k, v in criteria.items()}
            pruned, kept, total = _prune_criteria(raw, task_text, MAX_CHOICES, DESC_CHARS)
            if kept < total:
                instructions = (instructions + " ").strip()
                instructions += (
                    f"(Only the {kept} most task-relevant controls of {total} are listed.)"
                )
                info[name] = {"kept": kept, "total": total}
            has_input = any(label.startswith(("type_", "select_")) for label in pruned)
            has_click = any(label.startswith("click_") for label in pruned)
            if has_input and has_click:
                # Small local models need the routing rule spelled out; the allowed
                # answers themselves are still enforced at the logit level. The rule
                # flips between "enter the query" and "pick the result" based on the
                # current URL, which is what separates the two observed failure modes.
                url = ""
                if isinstance(state, dict):
                    page = state.get("current_page")
                    if isinstance(page, dict):
                        url = str(page.get("url", ""))
                if _SEARCH_URL_RE.search(url):
                    instructions += (
                        " Search results are already shown; click the option whose label"
                        " matches the item the task is looking for."
                    )
                else:
                    instructions += (
                        " Prefer type_* to enter the query into the text field; click the"
                        " option whose label best matches the task; use scroll_down only"
                        " when the needed control is not visible."
                    )
            if has_click:
                task_tokens = _token_set(task_text)
                matches: list[str] = []
                for label, description in pruned.items():
                    if not label.startswith("click_"):
                        continue
                    if _token_set(description) & task_tokens:
                        matches.append(f"{label} ({description[:40]})")
                    if len(matches) == 3:
                        break
                if matches:
                    instructions += " Possibly matching options: " + "; ".join(matches) + "."
            fields[name] = {"type": "enum", "description": instructions, "choices": pruned}
            kinds[name] = "choice"
            info.setdefault(name, {})["labels"] = list(pruned)[:48]
            info.setdefault(name, {})["top"] = [
                f"{label}={description[:70]}" for label, description in list(pruned.items())[:8]
            ]
        elif qtype == "noul":
            spec: dict[str, Any] = {"type": "boolean", "description": instructions}
            if isinstance(criteria, dict):
                spec["choices"] = {str(k).lower(): str(v)[:DESC_CHARS] for k, v in criteria.items()}
            fields[name] = spec
            kinds[name] = "noul"
        else:
            # jev-browser currently only sends choice + noul. Fail loudly rather
            # than guessing for score/unknown shapes.
            raise ValueError(f"unsupported question type {qtype!r} for {name!r}")

    return Schema(fields), kinds, info


def _answers_from_result(result: Any, kinds: dict[str, str]) -> dict[str, Any]:
    answers: dict[str, Any] = {}
    for name, field_value in result.items():
        kind = kinds.get(name, "choice")
        distribution = dict(getattr(field_value, "distribution", {}) or {})
        if not distribution:
            distribution = {str(field_value.value): float(field_value.probability)}

        if kind == "choice":
            answers[name] = {
                "type": "choice",
                "choice": str(field_value.value),
                "probabilities": {str(k): float(v) for k, v in distribution.items()},
                "confidence": round(float(field_value.probability), 6),
            }
        elif kind == "noul":
            if "true" in {str(k).lower() for k in distribution}:
                lookup = {str(k).lower(): float(v) for k, v in distribution.items()}
                p_true = lookup["true"] + lookup.get("yes", 0.0)
            else:
                p_true = float(field_value.probability) if field_value.value is True else 1.0 - float(field_value.probability)
            answers[name] = {"type": "noul", "noul": round(min(max(p_true, 0.0), 1.0), 6)}
    return answers


# --------------------------------------------------------------------------- #
# Typing model (OpenAI-compatible text helper)
# --------------------------------------------------------------------------- #

class _TypingModel:
    """A tiny local instruction-following model for 'type this text' calls.

    jev-browser asks for at most ~48 output tokens, a few times per run. Greedy
    decoding keeps it deterministic and fast.
    """

    def __init__(self, model_id: str, device: str | None = None, dtype: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self.model_id = model_id
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        if dtype is None:
            dtype = "float16" if self.device == "cuda" else "float32"
        self.torch_dtype = getattr(torch, dtype)

        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=self.torch_dtype)
        self.model.to(self.device)
        self.model.eval()

    SYSTEM_PROMPT = (
        "You are a precise text-entry helper inside a browser agent. "
        "Reply with only the exact text to type. No quotes, no explanations, no extra words."
    )

    @staticmethod
    def _sanitize(text: str) -> str:
        text = text.strip().strip("\"'`").strip()
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s*\bSTOP\b\s*$", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*[.;,]\s*$", "", text)
        return text.strip()[:120]

    def complete(self, messages: list[dict[str, str]], max_new_tokens: int = 48) -> tuple[str, int, int]:
        torch = self._torch
        if not any(message.get("role") == "system" for message in messages if isinstance(message, dict)):
            messages = [{"role": "system", "content": self.SYSTEM_PROMPT}, *messages]
        prompt = self.tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
        with torch.no_grad(), TYPING_LOCK:
            output = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=self.tokenizer.eos_token_id,
            )
        generated = output[0][inputs["input_ids"].shape[1]:]
        raw = self.tokenizer.decode(generated, skip_special_tokens=True)
        return self._sanitize(raw), int(inputs["input_ids"].shape[1]), int(generated.shape[0])


# --------------------------------------------------------------------------- #
# HTTP layer
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    server_version = SERVER_VERSION

    # -- helpers ----------------------------------------------------------- #

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("content-length", "0") or 0)
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError(f"content-length must be 1..{MAX_BODY_BYTES}")
        raw = self.rfile.read(length)
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("body must be a JSON object")
        return data

    def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout clean
        return

    # -- routes ------------------------------------------------------------ #

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            with STATS_LOCK:
                stats = dict(STATS)
            free_gb = _free_vram_gb()
            self._send(200, {
                "ok": DECIDER is not None,
                "model": DECIDER.model_id if DECIDER else None,
                "typing_model": TYPING.model_id if TYPING else None,
                "typing_device": TYPING.device if TYPING else None,
                "free_vram_gb": round(free_gb, 2) if free_gb is not None else None,
                "busy": bool(DECIDER and DECIDER._lock.locked()),
                **stats,
            })
        else:
            self._send(404, {"error": "use POST /v1/systemone or POST /v1/chat/completions"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/v1/systemone":
            self._handle_systemone()
        elif self.path == "/v1/chat/completions":
            self._handle_chat()
        else:
            self._send(404, {"error": "use POST /v1/systemone or POST /v1/chat/completions"})

    def _handle_systemone(self) -> None:
        if DECIDER is None:
            self._send(503, {"error": "engine not ready", "retry": True})
            return
        try:
            body = self._read_json()
            state = body.get("state")
            questions = body.get("questions")
            if not isinstance(questions, dict) or not questions:
                raise ValueError("questions must be a non-empty object")
            context = _render_state(state)
            schema, kinds, info = _questions_to_schema(questions, state)

            # Restate available text controls compactly; a 0.5B model often misses
            # them when they are only reachable through the criteria map.
            action = questions.get("action") or {}
            criteria = action.get("criteria") if isinstance(action, dict) else None
            if isinstance(criteria, dict):
                typeables = [
                    (str(label), str(desc)[:DESC_CHARS])
                    for label, desc in criteria.items()
                    if str(label).startswith(("type_", "select_"))
                ][:12]
                if typeables:
                    listing = "; ".join(f"{label}={desc}" for label, desc in typeables)
                    context += f"\nTEXT/CHOICE CONTROLS: {listing}"
        except Exception as exc:  # noqa: BLE001 - contract errors are 400s
            _bump("errors")
            self._send(400, {"error": f"bad request: {exc}"})
            return

        started = time.perf_counter()
        try:
            result = DECIDER.decide(context, schema)
        except Exception as exc:  # noqa: BLE001
            _bump("errors")
            self._send(500, {"error": f"engine failure: {exc}"})
            return

        wall_ms = (time.perf_counter() - started) * 1000
        _bump("systemone")

        if wall_ms > 5000:
            free_gb = _free_vram_gb()
            hint = f" (free VRAM: {free_gb:.2f} GB)" if free_gb is not None else ""
            _log(f"WARNING: decision took {wall_ms / 1000:.1f}s{hint} - GPU memory pressure "
                 f"is the usual cause; close GPU apps or use a smaller model")

        answers = _answers_from_result(result, kinds)
        if GOAL_TITLE_MATCH and "goal_done" in answers and isinstance(answers["goal_done"], dict):
            token = _goal_title_match(state)
            if token:
                current = float(answers["goal_done"].get("noul", 0.0))
                boosted = max(current, 0.92)
                if boosted > current:
                    answers["goal_done"]["noul"] = round(boosted, 6)
                    answers["goal_done"]["title_match"] = token
                    _log(f"goal_done {current:.3f} -> {boosted:.3f} (task item '{token}' found in page title/url)")

        _log(
            f"systemone prompt_tokens={result.telemetry.get('prompt_tokens')} "
            f"latency={result.latency_ms:.0f}ms wall={wall_ms:.0f}ms "
            f"pruned={info if info else 'no'}"
        )
        self._send(200, {
            "answers": answers,
            "usage": {
                "input_tokens": int(result.telemetry.get("prompt_tokens", 0)),
                "output_tokens": 0,
            },
            "model": result.model,
            "latency_ms": round(result.latency_ms, 1),
            "wall_ms": round(wall_ms, 1),
            "calibrated": bool(result.calibrated),
        })

    def _handle_chat(self) -> None:
        if TYPING is None:
            _bump("errors")
            self._send(503, {"error": "typing model not loaded (skipped for VRAM or --no-typing); "
                                      "restart the bridge with --typing", "retry": False})
            return
        try:
            body = self._read_json()
            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                raise ValueError("messages must be a non-empty array")
            max_new = int(body.get("max_tokens") or body.get("max_completion_tokens") or 64)
            if LOGGING:
                _log("typing messages=" + json.dumps(messages, ensure_ascii=False)[:700])
            text, prompt_tokens, completion_tokens = TYPING.complete(messages, max_new_tokens=min(max_new, 128))
            text = _typing_fallback(text, messages)
        except Exception as exc:  # noqa: BLE001
            _bump("errors")
            self._send(500, {"error": f"typing failure: {exc}"})
            return

        _bump("typing")
        self._send(200, {
            "id": f"chatcmpl-local-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": TYPING.model_id,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        })


# --------------------------------------------------------------------------- #
# Startup
# --------------------------------------------------------------------------- #

def main(argv: list[str] | None = None) -> int:
    global DECIDER, TYPING

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--model", default="Qwen/Qwen2.5-0.5B-Instruct",
                        help="decision model for the parallel-decisions engine")
    parser.add_argument("--device", default=None, help="torch device (default: cuda when available)")
    parser.add_argument("--dtype", default=None, help="torch dtype (default: float16 on CUDA, else float32)")
    parser.add_argument("--queue-timeout", type=float, default=120.0,
                        help="lock wait seconds for the engine (0 = fail fast)")
    parser.add_argument("--typing-model", default="Qwen/Qwen2.5-0.5B-Instruct",
                        help="local model used for the OpenAI-compatible typing endpoint")
    parser.add_argument("--no-typing", action="store_true", help="do not load the typing model")
    parser.add_argument("--typing", action="store_true",
                        help="force-load the typing model even when VRAM is tight "
                             "(default: auto-skip below the headroom threshold)")
    parser.add_argument("--force-vram", action="store_true",
                        help="load even when free VRAM is below the model + headroom estimate")
    parser.add_argument("--max-choices", type=int, default=int(os.environ.get("LOCAL_JEV_MAX_CHOICES", "40")),
                        help="element actions kept per step after task-relevance pruning (default 40)")
    parser.add_argument("--desc-chars", type=int, default=int(os.environ.get("LOCAL_JEV_DESC_CHARS", "64")),
                        help="per-option description character budget (default 64)")
    parser.add_argument("--quiet", action="store_true", help="suppress per-request logs")
    parser.add_argument("--no-goal-title-match", action="store_true",
                        help="disable the deterministic goal stop when a task item appears in the page title/URL")
    args = parser.parse_args(argv)

    global MAX_CHOICES, DESC_CHARS, LOGGING, GOAL_TITLE_MATCH
    MAX_CHOICES = max(5, args.max_choices)
    DESC_CHARS = max(16, args.desc_chars)
    LOGGING = not args.quiet
    GOAL_TITLE_MATCH = not args.no_goal_title_match

    import torch  # noqa: F401  (import early for a clean error before serving)
    from parallel_decisions import Decider

    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    dtype = args.dtype or ("float16" if device == "cuda" else "float32")

    # VRAM headroom guard: refuse a load that clearly cannot fit, and warn loudly
    # when the card is tight enough that Windows may start paging GPU memory.
    if device == "cuda":
        free_gb = _free_vram_gb()
        model_gb = _estimate_model_gb(args.model, 2 if dtype == "float16" else 4)
        if free_gb is not None:
            if free_gb < model_gb and not args.force_vram:
                print(f"[local-jev] refusing to load: {free_gb:.2f} GB VRAM free but the decision "
                      f"model needs ~{model_gb:.2f} GB. Close GPU apps or use --force-vram.", file=sys.stderr)
                return 2
            if free_gb < model_gb + VRAM_HEADROOM_GB:
                print(f"[local-jev] WARNING: {free_gb:.2f} GB VRAM free, ~{model_gb:.2f} GB model "
                      f"+ {VRAM_HEADROOM_GB:.1f} GB headroom recommended. Decisions may be 10-20x "
                      f"slower while Windows pages GPU memory.", file=sys.stderr)

    print(f"[local-jev] loading decision engine: {args.model} on {device} ({dtype})", file=sys.stderr)
    DECIDER = Decider(
        model_id=args.model,
        backend="torch",
        torch_device=device,
        torch_dtype=dtype,
        cuda_graph=False,
        lock_timeout_s=args.queue_timeout,
    )
    DECIDER.load()
    print(f"[local-jev] engine ready: {DECIDER.model_id}", file=sys.stderr)

    if args.no_typing:
        print("[local-jev] typing model disabled; jev-browser falls back to its heuristic", file=sys.stderr)
    else:
        free_gb = _free_vram_gb() if device == "cuda" else None
        typing_gb = _estimate_model_gb(args.typing_model, 2 if dtype == "float16" else 4)
        tight = free_gb is not None and free_gb < typing_gb + 1.0
        if tight and not args.typing:
            print(f"[local-jev] typing model skipped: {free_gb:.2f} GB VRAM free, ~{typing_gb + 1.0:.2f} GB "
                  f"needed. jev-browser falls back to its keyword heuristic "
                  f"(force with --typing).", file=sys.stderr)
            TYPING = None
        else:
            if tight:
                print(f"[local-jev] WARNING: loading the typing model with only {free_gb:.2f} GB free "
                      f"(--typing forced)", file=sys.stderr)
            print(f"[local-jev] loading typing model: {args.typing_model}", file=sys.stderr)
            try:
                TYPING = _TypingModel(args.typing_model, device=device, dtype=dtype)
                print(f"[local-jev] typing ready: {TYPING.model_id} on {TYPING.device}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001 - typing is optional
                TYPING = None
                print(f"[local-jev] typing model failed to load ({exc}); continuing without it", file=sys.stderr)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[local-jev] listening on http://{args.host}:{args.port}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
