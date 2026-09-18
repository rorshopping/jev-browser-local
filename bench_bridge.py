"""Time the local JEV bridge with a realistic jev-browser-sized state."""
import json
import time
import urllib.request

N = 240
elements = [
    {"id": f"e{i}", "description": f'a "Link number {i} about coffee and drinks" -> en.wikipedia.org/wiki/Page_{i}'}
    for i in range(1, N + 1)
]
criteria = {f"click_e{i}": elements[i - 1]["description"] for i in range(1, N + 1)}
criteria.update({
    "scroll_down": "Scroll down one screen to reveal more of the page",
    "scroll_up": "Scroll up one screen",
    "back": "Go back to the previous page; this branch is wrong",
    "done": "The task is already complete; stop here",
})
state = {
    "task": "Search Wikipedia for the espresso-based drink called Ristretto and stop when you are on that article",
    "current_page": {"url": "https://en.wikipedia.org/wiki/Main_Page", "title": "Wikipedia, the free encyclopedia"},
    "page_text_excerpt": "From today's featured article. " * 60,
    "interactive_elements": elements,
    "element_list_truncated": False,
    "no_interactive_elements": False,
    "history": [{"step": i, "action": f"click_e{i}", "outcome": "navigated"} for i in range(1, 6)],
}
questions = {
    "action": {
        "type": "choice",
        "instructions": "Which single action best advances the task on the current page?",
        "criteria": criteria,
    },
    "goal_done": {
        "type": "noul",
        "instructions": "The task's goal has been achieved: the current page and history show the sought outcome",
        "criteria": {"true": "The page being viewed is the sought destination", "false": "The goal is not yet achieved"},
    },
    "stuck": {
        "type": "noul",
        "instructions": "The actions so far are not making progress toward the task",
        "criteria": {"true": "Recent actions repeat", "false": "Progress is visible"},
    },
}
payload = json.dumps({"model": "jev-latest", "state": state, "questions": questions}).encode()

for run in (1, 2, 3):
    req = urllib.request.Request(
        "http://127.0.0.1:8768/v1/systemone",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.load(resp)
    wall = time.perf_counter() - started
    print(f"run {run}: wall={wall*1000:.0f}ms engine={body.get('latency_ms')}ms "
          f"prompt_tokens={body['usage']['input_tokens']} action={body['answers']['action']['choice']} "
          f"conf={body['answers']['action']['confidence']}")
