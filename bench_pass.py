"""Where does the suffix/pass time go for a 240-choice schema?"""
import time

import parallel_decisions.engine_torch as et
from parallel_decisions import Decider, Schema

orig_pass = et.TorchRuntime._batched_pass_eager
orig_broadcast = et.TorchRuntime.broadcast
stats = {"pass_calls": 0, "pass_s": 0.0, "rows": 0, "broadcast_calls": 0, "broadcast_s": 0.0}


def timed_pass(self, cache, rows, pad_id):
    started = time.perf_counter()
    result = orig_pass(self, cache, rows, pad_id)
    stats["pass_calls"] += 1
    stats["pass_s"] += time.perf_counter() - started
    stats["rows"] += len(rows)
    return result


def timed_broadcast(self, cache, n):
    started = time.perf_counter()
    result = orig_broadcast(self, cache, n)
    stats["broadcast_calls"] += 1
    stats["broadcast_s"] += time.perf_counter() - started
    return result


et.TorchRuntime._batched_pass_eager = timed_pass
et.TorchRuntime.broadcast = timed_broadcast

decider = Decider(model_id="Qwen/Qwen2.5-0.5B-Instruct", backend="torch",
                  torch_device="cuda", torch_dtype="float16", cuda_graph=False,
                  lock_timeout_s=300)
decider.load()

criteria = {f"click_e{i}": f'a "Link number {i} about coffee and drinks" -> en.wikipedia.org/wiki/Page_{i}'
            for i in range(1, 241)}
criteria.update({"scroll_down": "Scroll down", "scroll_up": "Scroll up",
                 "back": "Go back", "done": "Stop"})
schema = Schema({
    "action": {"type": "enum", "description": "Which action advances the task?",
               "choices": criteria},
    "goal_done": {"type": "boolean", "description": "Goal achieved", "choices": {"true": "yes", "false": "no"}},
    "stuck": {"type": "boolean", "description": "No progress", "choices": {"true": "yes", "false": "no"}},
})
context = "TASK: find the espresso article\nPAGE: Wikipedia (en.wikipedia.org)"

started = time.perf_counter()
result = decider.decide(context, schema)
wall = time.perf_counter() - started
print(f"decide wall={wall:.2f}s engine={result.latency_ms:.0f}ms prefill={result.prefill_ms:.0f}ms pass={result.pass_ms:.0f}ms")
print(f"batched_pass calls={stats['pass_calls']} rows={stats['rows']} time={stats['pass_s']:.2f}s")
print(f"broadcast calls={stats['broadcast_calls']} time={stats['broadcast_s']:.2f}s")
