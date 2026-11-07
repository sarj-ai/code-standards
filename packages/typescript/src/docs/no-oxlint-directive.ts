/** @fileoverview no-oxlint-directive — the documentation and executable examples of `@sarj/no-oxlint-directive`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_OXLINT_DIRECTIVE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Write every suppression directive with the `eslint-*` spelling.",
  rationale:
    "Oxlint honors both `oxlint-*` and `eslint-*` directive comments. With two spellings, finding every suppression in a repository takes two searches, and the same directive reads differently from file to file. One spelling keeps suppressions findable and reviewable alike; `eslint-*` is the spelling existing code already uses.",
  remediation:
    "Rename the directive prefix from `oxlint-` to `eslint-`; the rule list and the description stay as they are.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Only directive comments that start with `oxlint-disable`, `oxlint-disable-next-line`, `oxlint-disable-line` or `oxlint-enable` are reported. A directive that disables this rule itself, or every rule, hides its own report; the Standards runtime checks those separately.",
  ],
  references: ["https://oxc.rs/docs/guide/usage/linter/ignore-comments"],
  examples: [
    {
      id: "oxlint-next-line",
      title: "An Oxlint-spelled directive",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "// oxlint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      fixedFiles: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "eslint-next-line",
      title: "The ESLint spelling",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "block-directives",
      title: "Rewrite block disable and enable directives",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* oxlint-disable no-console */\nconsole.log(report);\n/* oxlint-enable no-console */\n" }],
      fixedFiles: [{ path: "src/report.ts", source: "/* eslint-disable no-console */\nconsole.log(report);\n/* eslint-enable no-console */\n" }],
      focusPath: "src/report.ts",
      expectedCount: 2,
    },
    {
      id: "same-line",
      title: "Rewrite a same-line directive",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "console.log(report); // oxlint-disable-line no-console -- the CLI prints its report\n" }],
      fixedFiles: [{ path: "src/report.ts", source: "console.log(report); // eslint-disable-line no-console -- the CLI prints its report\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
    },
    {
      id: "prose-mention",
      title: "A comment that only mentions the directive is not one",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "// Never write oxlint-disable here.\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
    },
  ],
} as const satisfies RuleDocumentation;
