"""Prefill cost matrix: attention impl x logits_to_keep. Robust to per-variant OOM."""
import time
import traceback

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
N_TOKENS = 7160

tokenizer = AutoTokenizer.from_pretrained(MODEL)
base = "Classify JSON attributes:\n  \"action\": " + "Options: " + "; ".join(
    f'click_e{i}=a "Link number {i} about coffee and drinks" -> en.wikipedia.org/wiki/Page_{i}'
    for i in range(1, 240)
)
prompt = base + "\n<|im_start|>user\n(TASK and PAGE content)\n<|im_end|>\n<|im_start|>assistant\n{\n"
ids = tokenizer(prompt, return_tensors="pt")["input_ids"]
if ids.shape[1] < N_TOKENS:
    filler = tokenizer(" word" * (N_TOKENS - ids.shape[1]), add_special_tokens=False)["input_ids"]
    ids = torch.cat([ids, torch.tensor([filler])], dim=1)
ids = ids[:, :N_TOKENS].to("cuda")
print(f"prompt tokens: {ids.shape[1]}  mem_efficient_sdp={torch.backends.cuda.mem_efficient_sdp_enabled()}")

for impl in ("sdpa", "eager"):
    for keep in (None, 1):
        label = f"attn={impl:5s} logits_to_keep={keep}"
        try:
            model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.float16,
                                                          attn_implementation=impl).to("cuda").eval()
            kwargs = {"use_cache": True}
            if keep is not None:
                kwargs["logits_to_keep"] = keep
            with torch.no_grad():
                model(ids[:, :512], use_cache=False)
                torch.cuda.synchronize()
                torch.cuda.reset_peak_memory_stats()
                started = time.perf_counter()
                out = model(ids, **kwargs)
                torch.cuda.synchronize()
                elapsed = time.perf_counter() - started
            peak = torch.cuda.max_memory_allocated() / 1024**3
            shape = tuple(out.logits.shape)
            print(f"{label:34s} prefill={elapsed:6.2f}s  peak_alloc={peak:5.2f} GiB  logits={shape}")
            del out
        except Exception as exc:  # noqa: BLE001 - keep the matrix running
            print(f"{label:34s} FAILED: {type(exc).__name__}: {str(exc)[:120]}")
        finally:
            try:
                del model
            except Exception:
                pass
            torch.cuda.empty_cache()
            torch.cuda.reset_peak_memory_stats()
