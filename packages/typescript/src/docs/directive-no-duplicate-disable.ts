/** @fileoverview directive-no-duplicate-disable — the documentation and executable examples of `@sarj/directive-no-duplicate-disable`. */

import type { RuleDocumentation } from "../documentation.js";

export const DIRECTIVE_NO_DUPLICATE_DISABLE_DOCUMENTATION = {
  summary: "Disallow `eslint-disable` and `oxlint-disable` directives for rules that are already disabled there.",
  rationale:
    "A second disable directive for a rule that is already off changes nothing, and it stays behind as a stale exception when the first one is removed.",
  remediation: "Delete the duplicate directive, or the rule name it repeats.",
  category: "maintainability",
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/no-duplicate-disable.html"],
  examples: [
    {
      id: "duplicate-line-disable",
      title: "A line disable inside a block that already disables the rule",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report); // eslint-disable-line no-console -- the CLI prints its report\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "single-disable",
      title: "One directive per suppressed rule",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report);\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mixed-prefixes",
      title: "Oxlint and ESLint spellings disable the same rules",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "// oxlint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report); // eslint-disable-line no-console -- the CLI prints its report\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
