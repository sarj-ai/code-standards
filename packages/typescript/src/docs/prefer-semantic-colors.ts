/** @fileoverview prefer-semantic-colors — the documentation and executable examples of `@sarj/prefer-semantic-colors`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SEMANTIC_COLORS_DOCUMENTATION = {
  summary: "Enforce semantic color tokens over raw Tailwind palette classes, arbitrary color values, and inline color literals.",
  rationale: "Semantic tokens keep themes and product meaning consistent while raw colors couple components to a palette value.",
  remediation: "Replace raw palette and literal colors with the closest semantic design-system token or CSS variable.",
  category: "style",
  limitations: [
    "Class-composition helper objects use literal keys as class fragments; cva/tv configuration objects retain value traversal. Computed keys are not resolved. URL payloads are not color literals.",
    "Email, PDF, video-rendering, print-only, icon artwork, masks, gradients, stories, and explicitly configured non-token projects have targeted exclusions.",
    "Opaque-foreground checks are opt-in and require both a same-variant semantic background class and its package-local declared foreground token.",
  ],
  examples: [
    { id: "semantic-text-color", title: "Use a semantic color token", outcome: "no-match", files: [{ path: "src/notice.tsx", source: "const notice = <div className=\"text-destructive\" />;" }], focusPath: "src/notice.tsx", expectedCount: 0, public: true },
    { id: "raw-text-color", title: "Do not use a raw palette color", outcome: "match", files: [{ path: "src/notice.tsx", source: "const notice = <div className=\"text-red-500\" />;" }], focusPath: "src/notice.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
