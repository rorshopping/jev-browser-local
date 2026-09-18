export type JevProvider = "typesafe" | "openrouter" | "cloudflare" | "vercel";
export interface AskResult {
    answers: Record<string, any>;
    usage: {
        input_tokens: number;
        output_tokens: number;
    };
    provider: JevProvider;
    model: string;
}
export declare function askJev(state: unknown, questions: Record<string, unknown>, model: string, signal?: AbortSignal): Promise<AskResult>;
