/**
 * The primary Jev call for each step: three independent judgments over the
 * same state. A select action adds one second-stage call for its option (see
 * selectOptionQuestion), so "one call per step" means one primary call.
 * Patterns: fan-out (docs.typesafe.ai/patterns/fan-out.md) — the questions
 * cannot see each other's answers, which is what makes goal_done an honest
 * cross-check on the action Choice rather than a rationalization of it.
 */
export declare function stepQuestions(criteria: Record<string, string>): {
    action: import("@typesafe-ai/sdk").ChoiceQuestion<Record<string, string>>;
    goal_done: import("@typesafe-ai/sdk").NoulQuestion;
    stuck: import("@typesafe-ai/sdk").NoulQuestion;
};
/**
 * Second stage for native <select> elements, asked only when the step Choice
 * picked select_eN. Option labels are the defined set; Jev picks the value.
 * Two-stage pattern: docs.typesafe.ai (Choice cardinality is bounded at 255).
 */
export declare function selectOptionQuestion(elementDescription: string, options: string[]): import("@typesafe-ai/sdk").ChoiceQuestion<Record<string, string>>;
