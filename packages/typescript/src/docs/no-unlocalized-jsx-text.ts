/** @fileoverview no-unlocalized-jsx-text — the documentation and executable examples of `@sarj/no-unlocalized-jsx-text`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNLOCALIZED_JSX_TEXT_DOCUMENTATION = {
  summary:
    "Require translation for literal JSX text in opted-in localized interfaces.",
  rationale: "Literal UI copy cannot change with the selected language.",
  remediation:
    "Pass the user-facing message through the configured translation API, or explicitly exempt text that must remain literal.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Standalone rule activation opts into localization for the selected files. No particular locale or translation function name is required. Generated files, tests, fixtures and stories are excluded.",
    'Only direct JSX text and complete literal expression children containing Unicode letters are checked. Dynamic expressions are not proven translated. Text inside code and samp elements is treated as technical content; their user-facing attributes are still checked by the attribute rule. translate="no" and configured translation component imports are respected; nested translate="yes" re-enables checking.',
  ],
  examples: [
    {
      id: "literal-message",
      title: "Translate a user-facing message",
      outcome: "match",
      files: [{ path: "src/message.tsx", source: "<p>Hello</p>" }],
      focusPath: "src/message.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "translated-message",
      title: "Resolve the message through translation",
      outcome: "no-match",
      files: [{ path: "src/message.tsx", source: '<p>{t("hello")}</p>' }],
      focusPath: "src/message.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
