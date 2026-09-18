"""Profile the 240-choice decide to find the real pass-stage cost."""
import time

from parallel_decisions import Decider, Schema

decider = Decider(model_id="Qwen/Qwen2.5-0.5B-Instruct", backend="torch",
                  torch_device="cuda", torch_dtype="float16", cuda_graph=False,
                  lock_timeout_s=300)
decider.load()

criteria = {f"click_e{i}": f'a "Link {i}" -> en.wikipedia.org/wiki/Page_{i}' for i in range(1, 241)}
criteria.update({"scroll_down": "s", "scroll_up": "u", "back": "b", "done": "d"})
schema = Schema({
    "action": {"type": "enum", "description": "action", "choices": criteria},
    "goal_done": {"type": "boolean", "description": "goal", "choices": {"true": "y", "false": "n"}},
    "stuck": {"type": "boolean", "description": "stuck", "choices": {"true": "y", "false": "n"}},
})
context = "TASK: x\nPAGE: y"

decider.decide(context, schema)  # warmup / cache compile

import torch
from torch.profiler import ProfilerActivity, profile

started = time.perf_counter()
with profile(activities=[ProfilerActivity.CUDA, ProfilerActivity.CPU]) as prof:
    result = decider.decide(context, schema)
    torch.cuda.synchronize()
wall = time.perf_counter() - started
print(f"decide wall={wall:.2f}s engine={result.latency_ms:.0f}ms prefill={result.prefill_ms:.0f}ms pass={result.pass_ms:.0f}ms")
print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=14))
