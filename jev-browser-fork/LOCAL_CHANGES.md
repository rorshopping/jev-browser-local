# Local changes vs upstream jev-browser 0.4.0

This is a **local fork** of `jkudish/jev-browser` at commit `257edfc` (v0.4.0,
MIT), kept in the project for one feature that has not been sent upstream:
**warm-browser / CDP mode**. No pull request was opened (user decision).

Diff summary (only `src/navigate.ts` and `src/cli.ts`):

- `NavigateOptions.cdpUrl` — connect to an already-running Chrome instead of
  launching one. Falls back to `JEV_BROWSER_CDP_URL`; `--cdp <url>` is also a
  CLI flag.
- When connected over CDP: reuse the browser's default context (persistent
  profile → HTTP cache, cookies, logins), set the viewport on the page, ignore
  `--record` (video capture needs a launched context), close only the page this
  run opened, and let `browser.close()` disconnect **without** shutting Chrome
  down.
- Everything else (decision loop, safety gates, extraction, MCP server) is
  unchanged from upstream.

Why: a cold Chromium pays a fresh-profile page load on every run. Measured with
`bench_warm.cjs` on this machine: cold launch 53 ms, cold first `goto`
2 893 ms; warm connect 41 ms, warm `goto` 95 ms (cache/DNS/TLS warmed by the
persistent profile). End-to-end on the Wikipedia Espresso task the saving was
~0.2–0.3 s because Wikipedia loads fast; the win is larger on heavy or
login-walled sites.

Build: `npm install && npm run build` (TypeScript only, no bundler).
Use: `node dist/index.js run "<task>" "<url>"` with `JEV_BROWSER_CDP_URL` set,
or the global `jev-browser` binary for the unmodified behavior.
