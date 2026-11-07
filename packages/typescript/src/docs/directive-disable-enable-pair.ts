/** @fileoverview directive-disable-enable-pair — the documentation and executable examples of `@sarj/directive-disable-enable-pair`. */

import type { RuleDocumentation } from "../documentation.js";

export const DIRECTIVE_DISABLE_ENABLE_PAIR_DOCUMENTATION = {
  summary: "Require an `eslint-enable` directive for every block `eslint-disable` or `oxlint-disable` directive.",
  rationale:
    "A block disable without an enable directive switches the rule off for the rest of the file, including code written long after the exception was reviewed.",
  remediation: "Add an `eslint-enable` directive for the same rules right after the code the exception covers.",
  category: "maintainability",
  limitations: ["An `oxlint-enable` directive closes an `eslint-disable` directive and the other way round, as Oxlint applies them."],
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/disable-enable-pair.html"],
  examples: [
    {
      id: "unclosed-block",
      title: "A block disable that runs to the end of the file",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      ruleOptions: [{ allowWholeFile: false }],
      public: true,
    },
    {
      id: "closed-block",
      title: "Close the block right after the excused code",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report);\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      ruleOptions: [{ allowWholeFile: false }],
      public: true,
    },
    {
      id: "oxlint-closes-eslint",
      title: "An Oxlint enable directive closes an ESLint disable directive",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report);\n/* oxlint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
    },
  ],
} as const satisfies RuleDocumentation;
