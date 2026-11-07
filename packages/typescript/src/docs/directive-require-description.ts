/** @fileoverview directive-require-description — the documentation and executable examples of `@sarj/directive-require-description`. */

import type { RuleDocumentation } from "../documentation.js";

export const DIRECTIVE_REQUIRE_DESCRIPTION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Require a `--` description on every directive comment, `eslint-*` or `oxlint-*`.",
  rationale:
    "A directive comment changes what the linter checks. Without a reason next to it, a reviewer cannot tell whether the exception still holds or can be removed.",
  remediation: "Append ` -- <reason>` to the directive comment, naming why the exception is safe here.",
  category: "maintainability",
  limitations: [
    "A description is any text after ` -- `; @sarj/no-vague-suppression-description judges its content.",
    "An `oxlint-*` directive follows the `ignore` entry of its `eslint-*` kind.",
  ],
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/require-description.html", "https://oxc.rs/docs/guide/usage/linter/ignore-comments"],
  examples: [
    {
      id: "undescribed-next-line",
      title: "A disable directive without a reason",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-console\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      ruleOptions: [{ ignore: [] }],
      public: true,
    },
    {
      id: "described-next-line",
      title: "Name the reason after `--`",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      ruleOptions: [{ ignore: [] }],
      public: true,
    },
    {
      id: "undescribed-oxlint-block",
      title: "Oxlint-spelled directives need a reason too",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* oxlint-disable no-console */\nconsole.log(report);\n/* oxlint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 2,
    },
    {
      id: "line-one-blanket-disable",
      title: "A blanket disable on the first line is reported",
      outcome: "match",
      files: [{ path: "src/generated.d.ts", source: "/* eslint-disable */\ndeclare const value: number;\n" }],
      focusPath: "src/generated.d.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
