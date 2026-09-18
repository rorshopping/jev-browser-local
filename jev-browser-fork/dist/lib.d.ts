/** Max elements offered to Jev per step. TypeSafe Choice supports up to 255 options. */
export declare const MAX_ELEMENTS = 240;
/** Raw interactive candidate as extracted from the page (already stamped with an attr). */
export interface RawElement {
    attr: string;
    tag: string;
    role: string;
    text: string;
    href: string;
    typeAttr: string;
    clickable: boolean;
    typeable: boolean;
    selectable?: boolean;
    options?: string[];
}
/** Pruned action-space element. */
export interface PageElement {
    id: string;
    attr: string;
    kind: "click" | "type" | "select";
    description: string;
    options?: string[];
}
export declare function isNoiseName(name: string): boolean;
export declare function isNoiseHref(href: string): boolean;
/** Filter, dedupe by destination, cap, and describe the action space for one step. */
export declare function buildActionSpace(raw: RawElement[]): {
    elements: PageElement[];
    truncated: boolean;
};
/** Jev Choice criteria for one step: element actions plus loop controls. */
export declare function buildCriteria(elements: PageElement[]): Record<string, string>;
export declare function selectorFor(el: PageElement): string;
/** Next-best action from a Choice distribution, excluding known-bad options. */
export declare function pickAlternate(probabilities: Record<string, number> | undefined, exclude: Set<string>): string | null;
/** Deterministic typing fallback when no small-LLM key is available. */
export declare function heuristicQuery(task: string): string;
/** jev-1.12 published pricing: input $0.042 per M tokens, output free. */
export declare const PRICE_PER_MTOK_IN = 0.042;
