/** @fileoverview require-button-accessible-name — the documentation and executable examples of `@sarj/require-button-accessible-name`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_BUTTON_ACCESSIBLE_NAME_DOCUMENTATION = {
  summary:
    "Require an accessible name on statically unnamed native or configured JSX buttons.",
  rationale:
    "An icon-only action without an accessible name cannot communicate its purpose to assistive technology.",
  remediation:
    "Provide meaningful visible or visually hidden text, aria-label, or aria-labelledby for the action.",
  category: "correctness",
  limitations: [
    "Native button and conventional Button elements are checked by default. Other custom buttons require exact module/export configuration; aliases and namespace imports are resolved by scope. Lucide icons are recognized by default; other icon modules are configurable.",
    "Composed JSX passed as props, render/asChild adapters, dynamic labels, children, unknown components, and prop spreads are left to runtime accessibility testing. Referenced IDs, CSS visibility, and meaningful wording are not verified. Generated files, tests, fixtures, and stories are excluded. No automatic labels are invented.",
    "A hidden prop with unshadowed undefined or exact void 0 does not hide the element or its children. Shadowed undefined and dynamic hidden values remain unproven.",
  ],
  examples: [
    {
      id: "unnamed-button",
      title: "Name an icon action",
      outcome: "match",
      files: [
        {
          path: "src/action.tsx",
          source: '<button><svg aria-hidden="true" /></button>',
        },
      ],
      focusPath: "src/action.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "named-button",
      title: "Provide the action name",
      outcome: "no-match",
      files: [
        {
          path: "src/action.tsx",
          source:
            '<button aria-label="Close"><svg aria-hidden="true" /></button>',
        },
      ],
      focusPath: "src/action.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
