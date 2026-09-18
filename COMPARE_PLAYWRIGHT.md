# Jev Browser (local engine) vs Playwright CLI — measured head-to-head

Task, both tools, same start page, same browser engine (Chromium, headless):

> *"Search Wikipedia for the espresso-based drink called Ristretto and stop when you are on that article"*
> starting at `https://en.wikipedia.org/wiki/Main_Page`

## Method

- **Playwright CLI** (`@playwright/cli`, this machine): the deterministic sequence
  `open Main_Page` → `fill "#searchInput" "Ristretto"` → `press Enter` → `snapshot` (verify).
  Two runs (cold daemon / warm daemon).
- **Jev Browser** pointed at the local engine (`local_jev_server.py`, Qwen2.5-1.5B
  decisions + 0.5B typing, chunked prefill + trie collision scoring):
  `run "<task>" <url> --max-steps 10` — evidence in `run-optimized-pruned.json`.
  Earlier builds of the same engine: `run-success.json` (5.9 s), `run-chunked-pruned.json` (4.6 s).

## Results

| | Playwright CLI (cold) | Playwright CLI (warm) | Jev Browser (local) |
| --- | --- | --- | --- |
| Wall time, full task | 4.67 s | **3.24 s** | **4.12 s** |
| Result | Ristretto article | Ristretto article | Ristretto article (`goal_achieved`, 3 steps) |
| Decided by | me (hardcoded `#searchInput` + Enter) | me | **the model**, 3 local decisions |
| Model calls | 0 | 0 | 3 (~0.6–0.8 s each, on the RTX 2060) |
| Tokens | 0 | 0 | 4 651 in / 0 out (local; $0) |
| Cloud cost | $0 | $0 | **$0** (hosted-TypeSafe price equivalent ≈ $0.0002) |
| Setup | `playwright-cli` + a known selector | same | Chromium + 1.5B local model (3 GB) + bridge |

Phase detail (JEV): browser launch + load ≈ 0.6–1.1 s (same class as Playwright's
1.29 s cold open), ~2.0 s of the run is local model decision time, the rest is the
same browser work (navigation, DOM settle, typing).

## What the numbers actually say

1. **Wall time is a wash** — both land at 3–5 s because the browser dominates and
   both drive the same engine. Playwright's warm run is the fastest (persistent
   daemon); JEV pays ~2 s of GPU "thinking" instead of needing a human/agent to
   already know the way.
2. **The intelligence is the difference.** `#searchInput` is an implementation
   detail a script must know. The JEV run finds the search field and the flow from
   a natural-language task and observed elements; it costs one local model load and
   ~0.7 s per decision. Site redesigns break selectors; descriptions survive them.
3. **If an LLM drives Playwright CLI** (the fair "agentic Playwright" case), the
   decision cost returns to the loop, cloud-side: published benchmarks on this
   machine class measured ~2.7 k input tokens per step for playwright-cli and
   180–350 s per task with frontier models (Outpost, "The Hidden Cost of Fewer
   Tokens", 2026-04; `imasimali/browser-tool-comparison`). The local engine does
   the same decisions offline, in ~0.7 s, with no token bill.
4. **Determinism vs adaptability.** Playwright executes exactly what it is told —
   the right choice for fixed flows, assertions, CI, and anything consequential.
   JEV trades determinism for adaptability: it can discover the flow, but it is
   also probabilistic (the 0.5B build failed this task; 1.5B succeeds reliably at
   3 steps — see the run history).
5. **They compose.** `jev-browser` is Playwright Chromium underneath: same executor,
   plus a decision layer. Playwright CLI stays the better tool when you know the
   path; the JEV layer pays when the path has to be discovered or described.

## Reproduce

```powershell
# Playwright CLI
playwright-cli -s=bench open "https://en.wikipedia.org/wiki/Main_Page"
playwright-cli -s=bench fill "#searchInput" "Ristretto"
playwright-cli -s=bench press Enter
playwright-cli -s=bench snapshot     # verify URL
playwright-cli -s=bench close

# Jev Browser (start the local engine first, see README)
$env:TYPESAFE_BASE_URL="http://127.0.0.1:8768"; $env:TYPESAFE_API_KEY="local-jev"
$env:JEV_BROWSER_TYPE_BASE_URL="http://127.0.0.1:8768/v1"
jev-browser run "Search Wikipedia for the espresso-based drink called Ristretto and stop when you are on that article" `
  "https://en.wikipedia.org/wiki/Main_Page" --max-steps 10
```

External agentic-Playwright figures are cited, not measured here; the only numbers
measured in this repo are the two Playwright CLI runs above and the JEV run
artifacts (`run-*.json`).
