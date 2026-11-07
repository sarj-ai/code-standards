/** @fileoverview require-svg-accessible-name — the documentation and executable examples of `@sarj/require-svg-accessible-name`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_SVG_ACCESSIBLE_NAME_DOCUMENTATION = {
  summary:
    "Require a name or explicit decorative semantics on inline SVG elements.",
  rationale:
    "Meaningful graphics need a name; decorative graphics should not add unnamed content to the accessibility tree.",
  remediation:
    "Add aria-label, aria-labelledby, or a direct title child; mark decorative graphics aria-hidden or presentational.",
  category: "correctness",
  limitations: [
    "Only intrinsic svg elements are checked. Dynamic labels, forwarded props, and dynamic title content remain runtime concerns. IDs, CSS visibility and graphic meaning are not inferred. Tests, stories, fixtures and generated files are excluded. No automatic title or decorative marker is invented.",
    "A hidden prop with unshadowed undefined or exact void 0 does not hide the element. Shadowed undefined and dynamic hidden values remain unproven.",
  ],
  examples: [
    {
      id: "unnamed-svg",
      title: "Name meaningful graphics",
      outcome: "match",
      files: [{ path: "src/chart.tsx", source: "<svg><path /></svg>" }],
      focusPath: "src/chart.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "decorative-svg",
      title: "Identify decorative graphics",
      outcome: "no-match",
      files: [
        {
          path: "src/chart.tsx",
          source: '<svg aria-hidden="true"><path /></svg>',
        },
      ],
      focusPath: "src/chart.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
