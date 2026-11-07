/** @fileoverview prefer-logical-tailwind-utilities — the documentation and executable examples of `@sarj/prefer-logical-tailwind-utilities`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_LOGICAL_TAILWIND_UTILITIES_DOCUMENTATION = {
  summary:
    "Prefer logical Tailwind utilities in explicitly opted-in bidirectional interfaces.",
  rationale:
    "Physical spacing and alignment remain on the same side when reading direction changes, producing incorrectly mirrored interfaces.",
  remediation:
    "Use the suggested logical utility; retain intentional physical geometry through allowUtilities or a scoped rule override.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Enable this rule only in scopes that support bidirectional layout. Standalone rule activation opts in. Insets require checkInsets:true; explicit rtl:/ltr: variants are exempt. No autofix changes physical coordinates.",
    "Only effective complete static JSX className values are inspected. Dynamic compositions, CSS, class factories and identifier references are not inferred. Tests, stories, fixtures and generated files are excluded.",
  ],
  examples: [
    {
      id: "physical-spacing",
      title: "Mirror layout spacing",
      outcome: "match",
      files: [{ path: "src/layout.tsx", source: '<div className="ml-2" />' }],
      focusPath: "src/layout.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "logical-spacing",
      title: "Use direction-aware spacing",
      outcome: "no-match",
      files: [{ path: "src/layout.tsx", source: '<div className="ms-2" />' }],
      focusPath: "src/layout.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
