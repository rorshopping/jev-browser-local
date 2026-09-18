# Jev Browser (local) vs Vercel agent-browser — how each one is fast, and what we can learn

Prompted by: *"identify how agent-browser by Vercel is doing this, compare, and maybe improve the JEV approach."*
All numbers below were measured on this machine unless marked **(cited)** or **(stated)**.
Costs are per task/run, not per hour.

## 1. How agent-browser gets its speed

From its README and docs (vercel-labs/agent-browser):

| Mechanism | What it buys |
| --- | --- |
| **Native Rust CLI** | Command parsing and process startup in sub-millisecond time; no Node boot per command |
| **Persistent daemon** | The browser stays launched between commands; each command is an IPC round trip (~100 ms class **(cited)** instead of a fresh Playwright launch) |
| **Accessibility-tree snapshots with stable refs** (`@e1`, `t1`) | Compact state (~200–400 tokens) vs playwright-cli's ~2.7 k-token snapshots **(cited: browser-tool-comparison)** |
| **Batch mode** | Many commands in one process invocation |
| **No model in the loop** | It never decides anything. An external agent (or you) supplies every selector and command |

**Key point: agent-browser is an executor.** Its speed work is about *process and
context overhead*, not intelligence. There is nothing to copy for "deciding
faster" — but two things transfer to us: the warm browser and the compact state
idea (we already send a compact state, ~1.4–1.6 k tokens).

## 2. Where our 4 seconds actually go (measured)

Successful run, task "Search Wikipedia for Ristretto" (`run-optimized-pruned.json`):

| Phase | Time | Share |
| --- | --- | --- |
| Browser start + first page load | ~0.3–1.0 s | 7–24% |
| 3 × local decision (1.5B, ~1.5 k-token prompts) | ~2.0 s | ~49% |
| Actions, DOM settle, typing model, stop | ~1.1 s | ~27% |
| **Total** | **4.1 s** | |

Note on the first row: Chromium *launch* is only ~50 ms on this machine; the
variable cost is the **first page load with an empty profile** (measured 2.89 s
cold in `bench_warm.cjs`), which the warm browser removes via HTTP cache/DNS/TLS
(95 ms warm).

Decision latency by model and prompt size (bridge measurements):

| Config | Prompt | Per decision |
| --- | --- | --- |
| Qwen2.5-0.5B | 900–1 800 tok | **180–500 ms** |
| Qwen2.5-1.5B | ~1 500 tok | **578–899 ms** |
| TypeSafe hosted Jev | — | **~300 ms (stated)**; launch claims 70–500 ms |
| 1.5B under VRAM pressure (7.7/8 GB used, WDDM paging) | ~1 500 tok | **10 000–14 000 ms** ⚠ |

A 0.5B *full run* looks fast (9–21 s for 10 steps) but **fails the task** — it
wanders through links and never types. Out of the box, speed without
task success is worthless, so 1.5B is the practical local floor here.

Trimming the action space (40 → 24 options, 64 → 48-char descriptions) made
decisions ~30% faster (394–603 ms) but **broke the task** under identical
conditions (`run-trimmed.json` vs `run-notype.json`). Pruning below ~40 trades
recall (the right link can fall out) and the 1.5B model's choice quality is
already fragile. Not a free win.

## 3. Cost, not just speed

| Approach | Per-run cost | Hardware / constraints |
| --- | --- | --- |
| Local JEV (this setup) | **$0** (electricity aside) | ~4 GB VRAM for both models, 3 GB disk, 8 GB card is *tight* with a desktop |
| TypeSafe hosted Jev | ~**$0.0002**/run (4.6 k tokens × $0.042/M, output free) | needs network + API key |
| Playwright CLI, hardcoded script | $0 | needs a human/agent who knows the selectors |
| Playwright/agent-browser + cloud LLM agent | ~$0.02–0.20/run (thousands of tokens per step) **(estimated from cited token counts × current model prices)** | cloud latency per step |

So: the cloud Jev's 0.3 s/call and our local 0.6–0.9 s/call are the *same order*;
the difference is a datacenter GPU vs an RTX 2060 driving a desktop. There is no
method gap to close — but there are headroom and plumbing gaps.

## 4. Ranked improvements for the local approach

1. **Warm browser — implemented locally** (`jev-browser-fork/` + `start_warm_chrome.ps1`,
   no upstream PR by request). Connect over CDP reuses a persistent profile: measured
   first-load 2.89 s → 0.095 s (`bench_warm.cjs`), ~0.2–0.3 s end-to-end on the
   Wikipedia task, plus logins survive between runs. Chrome stays up; only the page
   is closed per run.
2. **Don't prune below 40 options.** Measured: 24 options = ~30% faster
   decisions, failed task. Keep 40.
3. **VRAM headroom guard — implemented in the bridge.** Refuses impossible loads
   (`--force-vram` override), warns under model+1.5 GB, auto-skips the typing model
   when tight (`--typing` forces), exposes `free_vram_gb` on `/health`, and warns
   when a decision exceeds 5 s (the 10–15 s paging mode is 20× worse than any
   prompt tweak).
4. **Model slot.** 0.5B is ~2× faster per decision but fails; 1.5B succeeds at
   578–899 ms. A 7B (the accuracy tier in `quality-eval/`) needs >8 GB fp16, so
   it needs a bigger card.
5. **Hardware, if speed is the goal.** An sm80+ GPU removes the math-attention
   bottleneck entirely (flash kernels exist → no chunking needed, prefill ~10×
   faster) and 12–16 GB VRAM removes the paging cliff and fits 7B. This is the
   single biggest lever for local Jev latency *and* quality.

## 5. When each approach wins

| Need | Use |
| --- | --- |
| Fixed flow, CI, exact assertions | Playwright CLI / scripts |
| Natural-language task, path must be discovered, wants $0/inference and privacy | Local JEV (1.5B, 40 options) |
| Best-speed discovery with no GPU on the desk | Hosted Jev (~0.3 s/call, ~$0.0002/run) |
| Agent loop with cloud LLM budgets | agent-browser or playwright-cli as executor + cloud model |

## Evidence

All run artifacts live in `runs/`:
`run-optimized-pruned.json` (4.1 s success), `run-skill-check.json` (4.0 s warm +
typing success), `run-notype.json` (6.1 s success on the Espresso task),
`run-trimmed.json` (24-option failure), `run-05b-a/b.json` (0.5B failures),
`run-warm*.json` (first warm runs). `COMPARE_PLAYWRIGHT.md` has the Playwright
timings; bridge logs carry per-decision latencies.
