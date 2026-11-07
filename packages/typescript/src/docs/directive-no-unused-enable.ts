/** @fileoverview directive-no-unused-enable — the documentation and executable examples of `@sarj/directive-no-unused-enable`. */

import type { RuleDocumentation } from "../documentation.js";

export const DIRECTIVE_NO_UNUSED_ENABLE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Disallow `eslint-enable` and `oxlint-enable` directives for rules that are not disabled.",
  rationale: "An enable directive with nothing to close is left over from an exception that is gone, and it misleads readers into looking for one.",
  remediation: "Delete the enable directive, or the rule name it does not need.",
  category: "maintainability",
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/no-unused-enable.html"],
  examples: [
    {
      id: "stray-enable",
      title: "An enable directive with no disable directive before it",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "console.log(report);\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "paired-enable",
      title: "An enable directive that closes a disable directive",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report);\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "stray-oxlint-enable",
      title: "Oxlint-spelled enable directives are checked too",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "console.log(report);\n/* oxlint-enable */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
