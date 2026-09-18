export interface NavigateOptions {
    task: string;
    startUrl: string;
    maxSteps?: number;
    maxSeconds?: number;
    allowTyping?: boolean;
    format?: "text" | "markdown" | "html" | "aria";
    maxChars?: number;
    screenshot?: "final" | "none";
    recordDir?: string;
    /** CDP endpoint of an already-running Chrome (warm browser); defaults to JEV_BROWSER_CDP_URL. */
    cdpUrl?: string;
}
export interface StepRecord {
    step: number;
    t_ms?: number;
    proposed_action: string;
    executed_action: string | null;
    detail: string;
    recovery_reason?: string;
    action_error?: string;
    outcome: string;
    confidence: number | null;
    top_probability: number | null;
    goal_done: number;
    stuck: number;
}
export interface ConsoleEvent {
    step: number;
    type: "console_error" | "console_warning" | "page_error" | "request_failed";
    text: string;
    page: string;
}
export interface JevUsage {
    jev_calls: number;
    input_tokens: number;
    output_tokens: number;
    est_cost_usd: number;
}
import { type JevProvider } from "./provider.js";
export declare function navigate(options: NavigateOptions, externalSignal?: AbortSignal): Promise<{
    status: string;
    video_path: string | null;
    final_url: string;
    final_title: string;
    format: "text" | "markdown" | "html" | "aria";
    max_chars: number;
    page: {
        truncated: boolean;
        true_length: number;
        content: string;
    } | null;
    extraction_problems: string[] | undefined;
    steps: StepRecord[];
    console_events: ConsoleEvent[];
    console_events_dropped: number;
    usage: {
        jev_calls: number;
        input_tokens: number;
        output_tokens: number;
        est_cost_usd: number;
    };
    elapsed_ms: number;
    model: string;
    jev_provider: JevProvider | null;
    screenshot_base64_jpeg: string | null;
    error?: undefined;
} | {
    status: string;
    error: string;
    steps: StepRecord[];
    console_events: ConsoleEvent[];
    console_events_dropped: number;
    usage: {
        jev_calls: number;
        input_tokens: number;
        output_tokens: number;
        est_cost_usd: number;
    };
    elapsed_ms: number;
    model: string;
    jev_provider: JevProvider | null;
    video_path?: undefined;
    final_url?: undefined;
    final_title?: undefined;
    format?: undefined;
    max_chars?: undefined;
    page?: undefined;
    extraction_problems?: undefined;
    screenshot_base64_jpeg?: undefined;
}>;
