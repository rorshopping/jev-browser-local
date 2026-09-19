# jev-browser-local — a 100% local JEV engine for jev-browser

> **Based on** [jkudish/jev-browser](https://github.com/jkudish/jev-browser) v0.4.0 (MIT).
> The local fork in `jev-browser-fork/` adds warm-browser/CDP mode — see
> [`jev-browser-fork/LOCAL_CHANGES.md`](jev-browser-fork/LOCAL_CHANGES.md).
> **Engine:** [parallel-decisions](https://github.com/rorshopping/parallel-decisions) —
> local Jev-style parallel constrained decoding, no cloud API, $0 per decision.
> **Independent project**, not affiliated with TypeSafe AI; "Jev" / System One is their product.

This repo wires jev-browser (a browser CLI / MCP server that normally uses
TypeSafe's hosted Jev model for every step) to a **local** decision engine on an
RTX 2060 SUPER. No TypeSafe API, no OpenRouter, no OpenAI: every judgment and
every typed string is computed on this machine.

Final configuration: **Qwen2.5-1.5B-Instruct for decisions** and
**Qwen2.5-0.5B-Instruct for typing** (search queries).

The idea comes from Joey Kudish's X post (~2026-09-18): *"Built browser use using
TypeSafe's new jev model. It's really fast and very cheap and absolutely mogs a
traditional LLM for most browser tasks."* This repo keeps the "jev picks each
step" design and replaces the hosted model with the local engine.

**Measured result (2026-09-18, all local):**

```
jev-browser run "Search Wikipedia for the espresso-based drink called Ristretto
                 and stop when you are on that article" https://en.wikipedia.org/wiki/Main_Page
-> status: goal_achieved | final_url: https://en.wikipedia.org/wiki/Ristretto
-> 3 steps, 5.9 s, ~$0 (local)   [run-success.json]
```

Run artifacts (JSON traces, screenshots) live in `runs/`.

> Paths note: absolute paths in the commands below are from the development
> machine (Python venv under `parallel-decisions_wt/gpu`, engine checkout at
> `parallel-decisions`, installed editable into that venv). Adjust them for
> your setup — the bridge is a single self-contained Python file plus a CUDA
> venv with `parallel-decisions[torch]`.

| Component | Role |
| --- | --- |
| `@jkudish/jev-browser` 0.4.0 (installed globally) | CLI + MCP server: owns the browser loop, budgets, stop gates |
| `local_jev_server.py` | Local bridge: speaks TypeSafe's `POST /v1/systemone` contract → `parallel-decisions`, plus an OpenAI-compatible `/v1/chat/completions` typing endpoint |
| [`parallel-decisions`](https://github.com/rorshopping/parallel-decisions) + Qwen2.5-1.5B / 0.5B | Local parallel-constrained decoding on CUDA (1.5B decisions, 0.5B typing) |
| `pd.toml` | Engine configuration (torch / cuda / fp16 / no CUDA graphs) |
| `bench_engine.py`, `bench_bridge.py` | Latency probes used to tune the bridge |
| `dump_candidates.cjs` | Playwright diagnostic: what a jev-browser-style extraction sees on a page |
| `bench_warm.cjs` | Cold-launch vs CDP-connect timing probe for the warm browser |
| `start_bridge.ps1` | Starts the bridge with the right venv/PYTHONPATH and flags |
| `start_warm_chrome.ps1` / `stop_warm_chrome.ps1` | Headless Chrome with a persistent profile (CDP on 9333) |
| `jev-browser-fork/` | Local fork of jev-browser v0.4.0 adding warm-browser/CDP mode (see `LOCAL_CHANGES.md`) |
| `test_systemone_request.json`, `test_chat_request.json` | Protocol smoke tests |

## Security review (done before installing)

Checked the cloned source at `jkudish/jev-browser@257edfc` (v0.4.0, MIT):

- **No telemetry, no analytics, no phone-home.** Network calls go only to the
  selected JEV transport (here: overridden to localhost) and the configured
  typing provider (here: localhost).
- **Postinstall script** only runs `npx playwright install chromium` for the
  browser jev-browser drives. Opt out with `JEV_BROWSER_SKIP_BROWSER_DOWNLOAD=1`.
- **Model output cannot become code**: actions are resolved from a fixed list of
  observed elements stamped with `data-jev-id`; the model picks an *ID*, never a
  selector, coordinate, URL or script. Stop gates (done / goal / stuck / budgets)
  run in code *before* any action executes.
- **Input hardening**: password and file inputs are never offered; `javascript:`,
  `mailto:` and `tel:` links are filtered; action timeouts are capped by the run
  deadline.
- **Dependencies** are mainstream and declared (Playwright, MCP SDK, AI SDK
  providers, `@typesafe-ai/sdk` — the official TypeSafe SDK, MIT, by TypeSafe AI).
- Author is a verified, long-standing developer (GitHub since 2010, X `@jkudish`).

Caveats kept in mind: the project is days old (created 2026-09-17) and is early
software. Page content is untrusted data — it steers a model that drives clicks.
Keep tasks bounded, run headless, and don't hand it consequential actions
(payments, deletions, account changes) without supervision.

## Install (already done on this machine)

```powershell
npm install -g @jkudish/jev-browser@0.4.0
# jev-browser bundles playwright 1.63; fetch its browser build once:
node "$env:APPDATA\npm\node_modules\@jkudish\jev-browser\node_modules\playwright\cli.js" install chromium
```

## Run

Terminal 1 — the local JEV engine (1.5B decisions + 0.5B typing, ~20 s load, ~4 GB VRAM):

```powershell
& "C:\Users\Richard\Documents\Projects\parallel-decisions_wt\gpu\.venv\Scripts\python.exe" `
  "C:\Users\Richard\Documents\Projects\jev_browser_cli\local_jev_server.py" --port 8768 `
  --model "Qwen/Qwen2.5-1.5B-Instruct"
# smaller / faster alternative: --model Qwen/Qwen2.5-0.5B-Instruct
# no typing model at all:       --no-typing
# disable the title-match goal stop: --no-goal-title-match
```

Terminal 2 — jev-browser pointed at the local bridge (PowerShell):

```powershell
$env:TYPESAFE_API_KEY     = "local-jev"                              # dummy; the SDK requires a non-empty key
$env:TYPESAFE_BASE_URL    = "http://127.0.0.1:8768"                  # judgments -> local engine
$env:JEV_BROWSER_TYPE_BASE_URL = "http://127.0.0.1:8768/v1"          # typing   -> local model
$env:JEV_BROWSER_TYPE_MODEL    = "qwen2.5-0.5b-local"
$env:JEV_BROWSER_MODEL         = "local-jev-1.5b"

jev-browser run "Search Wikipedia for the espresso-based drink called Ristretto and stop when you are on that article" `
  "https://en.wikipedia.org/wiki/Main_Page" --max-steps 10 --max-seconds 180 --screenshot .\run.jpg
```

MCP registration for OpenCode (`opencode.json`):

```json
{
  "mcp": {
    "jev-browser": {
      "type": "local",
      "command": ["npx", "-y", "@jkudish/jev-browser"],
      "environment": {
        "TYPESAFE_API_KEY": "local-jev",
        "TYPESAFE_BASE_URL": "http://127.0.0.1:8768",
        "JEV_BROWSER_TYPE_BASE_URL": "http://127.0.0.1:8768/v1",
        "JEV_BROWSER_TYPE_MODEL": "qwen2.5-0.5b-local"
      }
    }
  }
}
```

## Why the bridge prunes the action space (read this before tuning)

Measured on this machine (`bench_engine.py`, Qwen2.5-0.5B fp16, CUDA):

| Action space | Prompt tokens | Prefill | Total decision |
| --- | --- | --- | --- |
| 16 elements | 913 | 0.18 s | 0.31 s |
| 64 elements | 2 161 | 2.1 s | 2.4 s |
| **240 elements (unpruned)** | **7 160** | **120 s** | **126 s** |
| 240 elements, descriptions ≤ 40 chars | 4 769 | 26 s | 27 s |

Prefill grows ~quadratically (eager attention on this GPU), and jev-browser's
TypeSafe SDK client has a **fixed 10-second per-request timeout** that cannot be
configured from outside. A 240-link page therefore cannot work unpruned.

The bridge ranks each step's element candidates by an IDF-weighted task relevance
(a match on "ristretto" beats a match on "wikipedia"), always keeps at least one
text/select control when the page has one, drops junk controls (menus, theme and
language toggles), orders the best matches first (small models have strong
position bias), and truncates descriptions:

- `LOCAL_JEV_MAX_CHOICES` / `--max-choices` (default **40**)
- `LOCAL_JEV_DESC_CHARS` / `--desc-chars` (default **64**)
- `--no-typing` — skip the typing model (jev-browser falls back to its keyword heuristic)

Result: ~1 500-token prompts, **~0.4 s (0.5B) / ~1 s (1.5B) per decision**, and the
completed 3-step run above in 5.9 s. Tune downward (e.g. 24) on very dense pages,
upward when the right element is being pruned away.

> **Update:** the engine's long-prompt bottleneck is fixed and merged (see
> "Engine fix" below) — the full 240-choice space now decides in ~1.3 s instead of
> 126 s. Pruning is still the default because the 1.5B model picks poorly when
> offered 240 options (measured: it fixates on the "Appearance" checkbox), not
> because of latency.

## Bridge behaviors that make a small local model work

These live in `local_jev_server.py`; each one exists because a naive mapping of
the TypeSafe contract onto a local 0.5–1.5B model failed in a reproducible way:

| Behavior | Why |
| --- | --- |
| **IDF-ranked, re-ordered, pruned action space** | Eager-attention prefill is the bottleneck; generic words like "wikipedia"/"article" must not outrank the specific term, and small models have strong position bias. |
| **History without action IDs or step numbers** | Echoing `click_e2` back in the context made the model re-pick the same option on every page (the decision suffix literally starts with `"action": "click_e`). |
| **Routing hint flips on search URLs** | "Prefer type_*" caused endless re-typing on the results page; "click the result" caused scrolling on the form page. The hint follows `state.current_page.url`. |
| **Proper-noun typing, not keyword soup** | Typing "espresso-based drink ristretto" produced a Wikipedia results page whose only Ristretto hit was *"page does not exist"*. Typing just `Ristretto` lands on the article. |
| **Deterministic goal gate** | The engine's boolean heads are unusable with Qwen2.5-1.5B (trivial true/false probes return 0.44–0.62 with no discrimination), so the *choice* head drives actions and code decides "goal reached" when a distinctive task token appears in the page title/URL (`--no-goal-title-match` turns this off). |
| **Typing label-echo guard** | The 0.5B typing model tends to echo the field label ("Search Wikipedia") instead of the value; the adapter strips label echoes and falls back to the proper noun. |

## Engine fix: chunked prefill + trie collision scoring (merged)

The prefill measurements above led to a root cause: on GPUs without an efficient
SDPA kernel (Turing and older — this RTX 2060 SUPER included), `math` is the only
available attention backend, so one prefill pass materialises the full
prompt×prompt score matrix. At 7.2k tokens that peaked at **7.4 GiB** — over the
card's free VRAM — and Windows silently paged the overflow into shared system
memory: 11 s became **120 s**, and the same cliff explains the intermittent
"zero free bytes" refusals in `GPU_SETUP.md`.

Profiling the remaining pass stage then showed the collision scorer running one
row per candidate through the prefix cache — 248 rows in 33 batched passes at
240 choices. It now scores a **trie** of the candidate sequences: only nodes with
children get a row (~25 rows / 4 passes), with the same summed log-probabilities.

Merged into parallel-decisions `main` on 2026-09-20 (`main` at `4582032`); two
commits:

- `1a249c7` chunked prefill (`torch_prefill_chunk`, default 2048, `PD_TORCH_PREFILL_CHUNK`, 0 disables)
- `4582032` trie-batched collision scoring (+ device-side candidate slicing)
- Full suite green: **234 passed, 3 skipped** (re-verified 2026-09-20 on the
  merged `main`); a new equivalence test pins the
  trie log-probabilities against the element-wise implementation within 1e-5.

| Measurement (Qwen2.5-0.5B fp16) | Before | After |
| --- | --- | --- |
| 7.2k-token prefill, standalone | 11.1 s / 7.4 GiB peak | **0.70 s / 1.6 GiB** (1024-token chunks) |
| Engine `decide`, 240 choices, desc 90 | 125.6 s | **1.33 s** (prefill 0.94 s, pass 0.36 s) |
| Unpruned 240-option e2e, 10 steps | 49.9 s | **22.2 s** (`run-optimized-240.json`; model still wanders) |
| Pruned e2e, Ristretto task | 5.9 s run | **4.1 s, goal_achieved** (`run-optimized-pruned.json`) |

The gpu venv resolves the engine through its editable install of the
parallel-decisions main checkout, so the bridge picks the fix up with no extra
configuration:

```powershell
& "...\parallel-decisions_wt\gpu\.venv\Scripts\python.exe" local_jev_server.py --port 8768 --model "Qwen/Qwen2.5-1.5B-Instruct"
```

Last-token logits differ by at most 0.04 from the single-pass path (fp16
reassociation), so answer probabilities shift slightly; the branch documents this
and keeps `torch_prefill_chunk = 0` as the exact previous behavior.

## Faster runs: warm browser + VRAM guard

**Warm browser** — `jev-browser-fork/` is a local fork of v0.4.0 (changes in
`LOCAL_CHANGES.md`, no upstream PR) that can attach to an already-running Chrome
over CDP:

```powershell
.\start_warm_chrome.ps1                                   # CDP on 127.0.0.1:9333, profile .chrome-profile
$env:JEV_BROWSER_CDP_URL = "http://127.0.0.1:9333"
node .\jev-browser-fork\dist\index.js run "<task>" "<url>"  # connect ~41 ms instead of a cold launch
```

What it actually buys (measured, `bench_warm.cjs`): the launch itself is only
~50 ms — the cost is the cold profile's first page load (**2.89 s cold vs
95 ms** with a warm cache/DNS/TLS). End-to-end on the Wikipedia task that is
~0.2–0.3 s (Wikipedia loads fast anyway); heavily cached or login-walled sites
gain more, and the persistent profile keeps site logins between runs.

**VRAM guard** — the bridge now:

- refuses to load when free VRAM is below the model estimate (`--force-vram` overrides),
- warns when free VRAM < model + 1.5 GB,
- auto-skips the typing model when the card is tight (`--typing` forces it),
- reports `free_vram_gb` in `/health`,
- warns per request when a decision exceeds 5 s — the paging symptom measured at
  **10–14 s vs 0.6–0.9 s healthy** when the card was full.

## AI skill

`~/.config/opencode/skills/jev-browser-local/SKILL.md` teaches an agent to start
the bridge, use the warm browser, run tasks, read the result JSON, watch VRAM,
and clean up GPU processes afterwards.

## Honest limits

- **The goal gate is a heuristic, not a model judgment.** The deterministic
  title/URL match is what stops the run reliably; it is tuned for "navigate to
  the named page" tasks and can fire early on tasks whose distinctive word
  (a city, a name) also appears in titles of intermediate pages. Disable it with
  `--no-goal-title-match` if you need strictly model-driven stops.
- The engine's **boolean (`noul`) heads are effectively unusable** with this
  model in this setup — verified with trivial questions where "the page is the
  Wikipedia main page" scored 0.46 on the main page. Enums/choices are what work.
  A proper fix belongs in the engine or a better decision model, not more prompt
  wording.
- `confidence` in the trace is the engine's **raw softmax** probability of the
  chosen option — a proxy, not TypeSafe's trained calibration.
- Decision quality still degrades on dense pages; if a target is missed, raise
  `--max-choices` (costs latency) or add the target word to the task text.
- `local_jev_server.py` binds 127.0.0.1 only and has no auth — keep it local.
- Qwen2.5-1.5B is ~3 GB in fp16 and fits this 8 GB card next to the 0.5B typing
  model; 7B (the accuracy tier for this engine) does not fit in fp16 here.
