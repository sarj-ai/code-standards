/** @fileoverview no-logical-or-fallback — the documentation and executable examples of `@sarj/no-logical-or-fallback`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_LOGICAL_OR_FALLBACK_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Use nullish defaults or explicit falsy-value checks instead of logical OR fallbacks.",
  rationale: "Logical OR falls back for empty strings, zero and false as well as missing values. This hides which values should actually receive a default.",
  remediation: "Use ?? for null or undefined. If an empty string, zero or false needs special handling, test that condition explicitly and preserve the intended behavior.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Requires TypeScript type information and strict null checks. Reports non-nullable string, number or bigint value fallbacks, including branded primitives and mixed primitive unions. Nullable inputs, including nullable booleans, remain owned by @typescript-eslint/prefer-nullish-coalescing; both rules are enabled in the managed strict config.",
    "Preserves non-nullable boolean aggregation, conditions, negations, left-hand && guards, and calls to the native unshadowed Boolean constructor, including erased TypeScript wrappers and globalThis/window/self access. Constant truthiness stays with no-unnecessary-condition. Unknown, any, unresolved generic, object-only and generated inputs are excluded. Strings and comments are never scanned as code.",
    "No automatic replacement is offered: replacing || with ?? would change empty-string or zero behavior. Non-nullable ||= expressions remain outside this companion rule.",
  ],
  references: ["https://typescript-eslint.io/rules/prefer-nullish-coalescing/"],
  examples: [
    { id: "logical-or-title", title: "Do not hide empty-string fallback behavior", outcome: "match", files: [{ path: "src/title.ts", source: 'export function title(value: string) { return value.trim() || "Untitled"; }' }], focusPath: "src/title.ts", expectedCount: 1, public: true },
    { id: "explicit-empty-title", title: "Preserve an intentional empty-string default", outcome: "no-match", files: [{ path: "src/title.ts", source: 'export function title(value: string) { const trimmed = value.trim(); return trimmed === "" ? "Untitled" : trimmed; }' }], focusPath: "src/title.ts", expectedCount: 0, public: true },
    { id: "boolean-aggregation", title: "Keep boolean OR", outcome: "no-match", files: [{ path: "src/access.ts", source: 'export function allowed(isAdmin: boolean, isOwner: boolean) { return isAdmin || isOwner; }' }], focusPath: "src/access.ts", expectedCount: 0, public: false },
  ],
} as const satisfies RuleDocumentation;
