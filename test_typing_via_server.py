"""A/B typing system prompts against the running bridge (no extra model load)."""
import json
import urllib.request

USER = (
    'A browser agent is performing this task: "Search Wikipedia for the espresso-based drink '
    'called Ristretto and stop when you are on that article". It must type into the '
    'input "Search Wikipedia" (type into this field) on https://en.wikipedia.org/wiki/Main_Page. '
    "Reply with ONLY the exact text to type (for a search box: a short search query; no quotes, no explanation)."
)

SYSTEMS = {
    "default": None,
    "B_field_label": (
        "You are a precise text-entry helper inside a browser agent. The field description names "
        "the field; it is NOT the text to type. Reply with only the exact string the task requires "
        "(for a search box: the search query only). No quotes, no explanation."
    ),
    "C_with_example": (
        "You are a precise text-entry helper inside a browser agent. The field description names "
        "the field; it is NOT the text to type. Reply with only the exact string the task requires. "
        "Example: task 'Find the article about Espresso', field 'input \"Search Wikipedia\"' -> Espresso. "
        "No quotes, no explanation."
    ),
}

for name, system in SYSTEMS.items():
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": USER}]
    payload = json.dumps({"model": "qwen2.5-0.5b-local", "messages": messages, "max_tokens": 48}).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8768/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.load(resp)
    print(f"{name:16s} -> {body['choices'][0]['message']['content']!r}")
