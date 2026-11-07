/** @fileoverview no-hand-rolled-spinner — the documentation and executable examples of `@sarj/no-hand-rolled-spinner`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_HAND_ROLLED_SPINNER_DOCUMENTATION = {
  summary: "Disallow intrinsic elements styled as Tailwind border-ring spinners outside the design-system implementation.",
  rationale: "One-off loading indicators duplicate a shared primitive and let accessibility and styling diverge.",
  remediation: "Render the design-system Spinner component instead.",
  category: "maintainability",
  limitations: ["Only effective static className values on div and span elements are inspected; Tailwind utilities are combined only when they are unprefixed or share one exact variant context, while a later spread makes the value unknown. Tests, stories, generated files, and the design-system implementation are excluded."],
  examples: [
    { id: "design-system-spinner", title: "Use the shared spinner", outcome: "no-match", files: [{ path: "src/loading-state.tsx", source: '<Spinner className="size-4" />' }], focusPath: "src/loading-state.tsx", expectedCount: 0, public: true },
    { id: "border-ring-spinner", title: "Do not rebuild a spinner", outcome: "match", files: [{ path: "src/loading-state.tsx", source: '<div className="size-4 animate-spin rounded-full border-2 border-t-transparent" />' }], focusPath: "src/loading-state.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
