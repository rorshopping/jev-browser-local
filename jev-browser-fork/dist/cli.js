// CLI: `jev-browser run "<task>" <start-url> [options]`
// Everything else (no args) starts the MCP stdio server (src/index.ts).
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { navigate } from "./navigate.js";
function parseArgs(argv) {
    const args = { task: undefined, startUrl: undefined };
    const positional = [];
    for (let i = 0; i < argv.length; i++) {
        const arg = argv[i];
        switch (arg) {
            case "--format":
                args.format = argv[++i];
                break;
            case "--max-chars":
                args.maxChars = Number(argv[++i]);
                break;
            case "--max-steps":
                args.maxSteps = Number(argv[++i]);
                break;
            case "--max-seconds":
                args.maxSeconds = Number(argv[++i]);
                break;
            case "--no-typing":
                args.allowTyping = false;
                break;
            case "--screenshot":
                args.screenshotPath = argv[++i];
                break;
            case "--no-screenshot":
                args.screenshot = "none";
                break;
            case "--record":
                args.recordPath = argv[++i];
                break;
            case "--cdp":
                args.cdpUrl = argv[++i];
                break;
            case "--help":
            case "-h":
                args.help = true;
                break;
            default:
                positional.push(arg);
        }
    }
    const [task, startUrl] = positional;
    return { ...args, task, startUrl };
}
const HELP = `jev-browser run "<task>" <start-url> [options]

Options:
  --format <text|markdown|html|aria>   Final page payload (default text)
  --max-chars <n>                      Override the format's character cap
  --max-steps <n>                      Hard step cap (default 24)
  --max-seconds <n>                    Wall-clock cap (default 180)
  --no-typing                          Disable typing into fields
  --screenshot <path>                  Write the final JPEG to this path
  --no-screenshot                      Skip the screenshot entirely
  --record <path>                      Record a video of the page; a .webm path
                                       saves to that file, any other value is a
                                       directory for Playwright's output
  --cdp <url>                          Connect to an already-running Chrome
                                       (e.g. http://127.0.0.1:9222) instead of
                                       launching one; also JEV_BROWSER_CDP_URL
  -h, --help                           Show this help

Result JSON is printed to stdout. Environment: TYPESAFE_API_KEY required;
JEV_BROWSER_* vars configure models and the typing provider.

Without "run", this binary starts the MCP stdio server.`;
export async function runCli(argv) {
    const args = parseArgs(argv);
    if (args.help || !args.task || !args.startUrl) {
        console.log(HELP);
        return args.help ? 0 : 1;
    }
    const { screenshotPath, recordPath, ...navigateArgs } = args;
    let recordDir;
    if (recordPath) {
        recordDir = recordPath.endsWith(".webm") ? await import("node:fs/promises").then((fs) => fs.mkdtemp("jev-browser-record-")) : recordPath;
    }
    const result = (await navigate({
        ...navigateArgs,
        screenshot: screenshotPath ? "final" : (args.screenshot ?? "final"),
        recordDir,
    }));
    if (recordPath?.endsWith(".webm") && result.video_path) {
        const fs = await import("node:fs/promises");
        // Playwright can flush the video for a moment after close; wait for the
        // source file to settle before copying, or the copy truncates.
        let size = -1;
        for (let i = 0; i < 20; i++) {
            const stat = await fs.stat(result.video_path).catch(() => null);
            const current = stat?.size ?? -1;
            if (current === size && current > 0)
                break;
            size = current;
            await new Promise((r) => setTimeout(r, 500));
        }
        await fs.copyFile(result.video_path, recordPath);
        result.video_path = recordPath;
    }
    if (screenshotPath && result.screenshot_base64_jpeg) {
        await mkdir(dirname(screenshotPath), { recursive: true });
        await writeFile(screenshotPath, Buffer.from(result.screenshot_base64_jpeg, "base64"));
        result.screenshot_path = screenshotPath;
    }
    // The CLI prints JSON; base64 screenshots belong in files, not terminals.
    delete result.screenshot_base64_jpeg;
    console.log(JSON.stringify(result, null, 2));
    return result.status === "error" ? 1 : 0;
}
//# sourceMappingURL=cli.js.map