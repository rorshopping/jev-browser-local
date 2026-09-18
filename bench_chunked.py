"""Proof of concept: chunked prefill bounds attention memory on sm75.

A causal transformer can read a long prompt in segments when it carries a KV
cache: each segment attends to everything before it plus its own causal window.
Peak attention memory becomes O(chunk^2) instead of O(prompt^2).
"""
import time

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
N = 7160

tokenizer = AutoTokenizer.from_pretrained(MODEL)
ids = tokenizer("Classify JSON attributes:\n" + " word" * N, return_tensors="pt")["input_ids"][:, :N].to("cuda")

model = AutoModelForCausalLM.from_pretrained(
    MODEL, dtype=torch.float16, attn_implementation="sdpa").to("cuda").eval()

with torch.no_grad():
    model(ids[:, :256], use_cache=False)
    torch.cuda.synchronize()
    torch.cuda.reset_peak_memory_stats()

    # Baseline: one pass over the full prompt
    started = time.perf_counter()
    out = model(ids, use_cache=True)
    torch.cuda.synchronize()
    single = time.perf_counter() - started
    single_peak = torch.cuda.max_memory_allocated() / 1024**3
    single_logits = out.logits[:, -1, :].float().clone()
    del out
    torch.cuda.empty_cache()

    # Chunked: 4 segments through one growing cache
    for chunk in (2048, 1024):
        torch.cuda.reset_peak_memory_stats()
        cache = None
        started = time.perf_counter()
        last = None
        for start in range(0, N, chunk):
            last = model(ids[:, start:start + chunk], past_key_values=cache, use_cache=True)
            cache = last.past_key_values
        torch.cuda.synchronize()
        elapsed = time.perf_counter() - started
        peak = torch.cuda.max_memory_allocated() / 1024**3
        diff = (last.logits[:, -1, :].float() - single_logits).abs().max().item()
        print(f"chunk={chunk:5d}  prefill={elapsed:6.2f}s  peak_alloc={peak:5.2f} GiB  "
              f"last-token logits max|diff| vs single={diff:.4f}")
        del last, cache
        torch.cuda.empty_cache()

print(f"single pass   prefill={single:6.2f}s  peak_alloc={single_peak:5.2f} GiB")
del model
torch.cuda.empty_cache()
