"""Direct engine latency probe for jev-browser-shaped schemas."""
import time

from parallel_decisions import Decider, Schema

decider = Decider(
    model_id="Qwen/Qwen2.5-0.5B-Instruct",
    backend="torch",
    torch_device="cuda",
    torch_dtype="float16",
    cuda_graph=False,
    lock_timeout_s=300,
)
decider.load()

context = (
    "TASK: Search Wikipedia for the espresso-based drink called Ristretto and stop when you are on that article\n"
    "PAGE: Wikipedia, the free encyclopedia (https://en.wikipedia.org/wiki/Main_Page)\n"
    "PAGE TEXT: " + ("From today's featured article. " * 60)
)


def make_schema(n: int, desc_chars: int) -> Schema:
    criteria = {}
    for i in range(1, n + 1):
        desc = f'a "Link number {i} about coffee and drinks" -> en.wikipedia.org/wiki/Page_{i}'
        criteria[f"click_e{i}"] = desc[:desc_chars]
    criteria["scroll_down"] = "Scroll down one screen to reveal more of the page"
    criteria["scroll_up"] = "Scroll up one screen"
    criteria["back"] = "Go back to the previous page; this branch is wrong"
    criteria["done"] = "The task is already complete; stop here"
    return Schema({
        "action": {"type": "enum", "description": "Which single action best advances the task?", "choices": criteria},
        "goal_done": {"type": "boolean", "description": "The goal has been achieved",
                      "choices": {"true": "sought page", "false": "not yet"}},
        "stuck": {"type": "boolean", "description": "No progress is being made",
                  "choices": {"true": "repeats", "false": "progress"}},
    })


for n, desc_len in ((16, 90), (64, 90), (240, 90), (240, 40), (240, 0)):
    schema = make_schema(n, desc_len)
    started = time.perf_counter()
    result = decider.decide(context, schema)
    wall = time.perf_counter() - started
    action = result["action"]
    print(
        f"N={n:3d} desc={desc_len:2d} wall={wall:7.2f}s engine={result.latency_ms:8.1f}ms "
        f"prefill={result.prefill_ms:7.1f} pass={result.pass_ms:7.1f} chunks={result.chunks} "
        f"prompt_tokens={result.telemetry.get('prompt_tokens')} choice={action.value} p={action.probability:.3f}"
    )
