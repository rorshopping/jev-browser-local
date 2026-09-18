// Compare cold launch vs CDP connect costs on this machine.
const { chromium } = require("C:/Users/Richard/Documents/Projects/jev_browser_cli/jev-browser-fork/node_modules/playwright");

async function timed(label, fn) {
  const started = Date.now();
  const result = await fn();
  console.log(`${label}: ${Date.now() - started} ms`);
  return result;
}

(async () => {
  // cold launch
  const browserCold = await timed("launch", () => chromium.launch({ headless: true }));
  const contextCold = await timed("newContext", () => browserCold.newContext({ viewport: { width: 1024, height: 640 } }));
  const pageCold = await timed("newPage", () => contextCold.newPage());
  await timed("goto", () => pageCold.goto("https://en.wikipedia.org/wiki/Main_Page", { waitUntil: "domcontentloaded" }));
  await browserCold.close();

  // warm connect
  const browserWarm = await timed("connectOverCDP", () => chromium.connectOverCDP("http://127.0.0.1:9333"));
  const contextWarm = await timed("contexts()[0]", async () => browserWarm.contexts()[0] ?? (await browserWarm.newContext()));
  const pageWarm = await timed("newPage", () => contextWarm.newPage());
  await timed("goto", () => pageWarm.goto("https://en.wikipedia.org/wiki/Main_Page", { waitUntil: "domcontentloaded" }));
  await pageWarm.close();
  await browserWarm.close();
  await timed("reconnect", () => chromium.connectOverCDP("http://127.0.0.1:9333"));
})();
