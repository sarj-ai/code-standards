/** @fileoverview directive-no-use — the documentation and executable examples of `@sarj/directive-no-use`. */

import type { RuleDocumentation } from "../documentation.js";

const ALLOW = [{ allow: ["eslint-disable-line", "eslint-disable-next-line", "eslint-env", "exported", "global", "globals"] }] as const;

export const DIRECTIVE_NO_USE_DOCUMENTATION = {
  summary: "Disallow directive comments, `eslint-*` or `oxlint-*`, except the allowed kinds.",
  rationale:
    "Block disables and inline rule configuration hide diagnostics for whole regions of a file. Allowing only line-scoped directives keeps each exception next to the code it excuses.",
  remediation:
    "Replace the directive with one of the allowed kinds, usually an `eslint-disable-next-line` comment that names the rule and the reason.",
  category: "maintainability",
  limitations: [
    "An `oxlint-*` directive follows the `allow` entry of its `eslint-*` kind; @sarj/no-oxlint-directive reports the spelling.",
    "Oxlint honors line comments such as `// eslint-disable`, so this rule reports them although ESLint ignores them.",
  ],
  references: ["https://eslint-community.github.io/eslint-plugin-eslint-comments/rules/no-use.html", "https://oxc.rs/docs/guide/usage/linter/ignore-comments"],
  examples: [
    {
      id: "block-disable",
      title: "A block disable hides every later line",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* eslint-disable no-console -- the CLI prints its report */\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      ruleOptions: ALLOW,
      public: true,
    },
    {
      id: "next-line",
      title: "Disable one line instead",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "// eslint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      ruleOptions: ALLOW,
      public: true,
    },
    {
      id: "oxlint-next-line",
      title: "The Oxlint spelling of an allowed kind is allowed",
      outcome: "no-match",
      files: [{ path: "src/report.ts", source: "// oxlint-disable-next-line no-console -- the CLI prints its report\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 0,
      ruleOptions: ALLOW,
    },
    {
      id: "inline-config",
      title: "Inline rule configuration is a directive",
      outcome: "match",
      files: [{ path: "src/report.ts", source: "/* eslint no-console: \"off\" -- the CLI prints its report */\nconsole.log(report);\n" }],
      focusPath: "src/report.ts",
      expectedCount: 1,
      ruleOptions: ALLOW,
    },
  ],
} as const satisfies RuleDocumentation;
