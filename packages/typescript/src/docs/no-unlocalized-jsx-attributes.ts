/** @fileoverview no-unlocalized-jsx-attributes — the documentation and executable examples of `@sarj/no-unlocalized-jsx-attributes`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNLOCALIZED_JSX_ATTRIBUTES_DOCUMENTATION = {
  summary:
    "Require translation for literal user-visible JSX attributes in opted-in localized interfaces.",
  rationale:
    "Accessible labels and placeholders must follow the interface language along with visible copy.",
  remediation:
    "Pass the user-facing message through the configured translation API, or explicitly exempt text that must remain literal.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Standalone rule activation opts into localization for the selected files. No particular locale or translation function name is required. Generated files, tests, fixtures and stories are excluded.",
    "Default attributes are title, placeholder, alt, aria-label and aria-description. Custom attribute names are configurable. ID-reference attributes are always excluded. Later spreads make values unknown; dynamic expressions are not proven translated.",
  ],
  examples: [
    {
      id: "literal-message",
      title: "Translate a user-facing message",
      outcome: "match",
      files: [
        { path: "src/message.tsx", source: '<input placeholder="Search" />' },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "translated-message",
      title: "Resolve the message through translation",
      outcome: "no-match",
      files: [
        {
          path: "src/message.tsx",
          source: '<input placeholder={t("search")} />',
        },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
