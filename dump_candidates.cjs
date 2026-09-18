// Dump the interactive candidates a jev-browser-style extraction would see.
const { chromium } = require("C:/Users/Richard/AppData/Roaming/npm/node_modules/@jkudish/jev-browser/node_modules/playwright");

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1024, height: 640 } });
  const url = process.argv[2];
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.waitForTimeout(1500);
  const data = await page.evaluate(() => {
    const SEL = 'a[href], button, input, textarea, select, [role="button"], [role="link"], [role="searchbox"], [role="textbox"]';
    const out = [];
    for (const el of document.querySelectorAll(SEL)) {
      const rects = el.getClientRects();
      if (!rects.length) continue;
      const style = getComputedStyle(el);
      if (style.display === "none" || style.visibility === "hidden") continue;
      const label = (el.getAttribute("aria-label") || el.getAttribute("placeholder") || el.getAttribute("title") || el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
      out.push(`${el.tagName.toLowerCase()} | ${label.slice(0, 70)} | ${(el.getAttribute("href") || "").slice(0, 60)}`);
    }
    return out;
  });
  console.log(`total candidates: ${data.length}`);
  const hits = data.filter((line) => /ristretto/i.test(line));
  console.log(`lines mentioning ristretto: ${hits.length}`);
  hits.slice(0, 10).forEach((line) => console.log("  HIT " + line));
  console.log("--- first 40 ---");
  data.slice(0, 40).forEach((line, i) => console.log(`${i + 1}. ${line}`));
  await browser.close();
})();
