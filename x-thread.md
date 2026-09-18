# X thread draft — jev-browser-local (5 posts)

1/
I built a 100% local Jev-style decision engine that drives a browser.

No cloud API: jev-browser picks every click/type step with my own parallel-decisions engine (Qwen 1.5B on an RTX 2060).

3 steps to land a Wikipedia article. ~4 s. $0.

2/
How: jev-browser asks TypeSafe-style systemone questions (choice + booleans). A local bridge answers them with parallel constrained decoding - all fields in one forward pass. Typing is a local 0.5B. One decision ~0.6-0.9 s on GPU.

3/
To make it fast I had to fix my engine:
- 240-option pages took 126 s to decide
- chunked prefill: 7.4 GB -> 1.6 GB peak, 11 s -> 0.7 s
- trie collision scoring: 33 passes -> 4

Now 240 choices decide in 1.3 s.

4/
Same task: hosted Jev ~0.3 s/call (~$0.0002/run), local 1.5B ~0.6-0.9 s/call ($0). Playwright CLI needs hardcoded selectors; this decides from a natural-language goal.

Honest limit: 0.5B is fast but fails multi-step tasks. 1.5B is the local floor; 7B doesn't fit 8 GB.

5/
Repo: bridge, warm-browser fork, VRAM guard, benchmarks, raw run traces:
github.com/rorshopping/jev-browser-local

Built on @jkudish's jev-browser (MIT fork), inspired by @typesafeai's Jev. Thanks Joey - this thing rips.
