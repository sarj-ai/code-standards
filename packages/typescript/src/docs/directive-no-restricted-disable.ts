/** @fileoverview directive-no-restricted-disable — the documentation and executable examples of `@sarj/directive-no-restricted-disable`. */

import type { RuleDocumentation } from "../documentation.js";

export const DIRECTIVE_NO_RESTRICTED_DISABLE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Disallow `eslint-disable` and `oxlint-disable` directives that turn off a restricted rule or every rule.",
  rationale:
    "Some rules guard policy that a local exception must not waive, such as the suppression rules themselves. A directive that disables every rule also disables those.",
  remediation: "Fix the reported code instead, or name only rules that may be disabled.",
  category: "maintainability",
  limitations: [
    "Options are gitignore-style patterns over rule IDs: `foo/*` matches every rule of plugin `foo`, a pattern without a slash also matches that rule name under any plugin, and `!` re-allows.",
    "A directive that names no rule is reported once, with the configured patterns as the rule name.",
  ],
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/no-restricted-disable.html"],
  examples: [
    {
      id: "restricted-rule",
      title: "Disabling a restricted rule",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      ruleOptions: ["no-console"],
      public: true,
    },
    {
      id: "unrestricted-rule",
      title: "Disabling a rule that is not restricted",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-debugger -- a breakpoint for the demo\ndebugger;\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      ruleOptions: ["no-console"],
      public: true,
    },
    {
      id: "oxlint-plugin-pattern",
      title: "A plugin pattern covers an Oxlint-spelled directive",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "// oxlint-disable-next-line @sarj/no-enum -- generated contract\nenum Mode { A }\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      ruleOptions: ["@sarj/*"],
    },
  ],
} as const satisfies RuleDocumentation;
