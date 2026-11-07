/** @fileoverview directive-no-aggregating-enable — the documentation and executable examples of `@sarj/directive-no-aggregating-enable`. */

import type { RuleDocumentation } from "../documentation.js";

export const DIRECTIVE_NO_AGGREGATING_ENABLE_DOCUMENTATION = {
  summary: "Disallow one `eslint-enable` or `oxlint-enable` directive closing several disable directives.",
  rationale:
    "When one enable directive closes several disable directives, removing one exception means editing a shared comment, and it is easy to re-enable a rule early or leave one off.",
  remediation: "Write one enable directive for each disable directive, naming the same rules.",
  category: "maintainability",
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/no-aggregating-enable.html"],
  examples: [
    {
      id: "shared-enable",
      title: "One enable directive closes two disable directives",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\n/* eslint-disable no-debugger -- a breakpoint for the demo */\nconsole.log(report);\ndebugger;\n/* eslint-enable */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "one-enable-each",
      title: "One enable directive for each disable directive",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\n/* eslint-disable no-debugger -- a breakpoint for the demo */\nconsole.log(report);\ndebugger;\n/* eslint-enable no-debugger */\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
