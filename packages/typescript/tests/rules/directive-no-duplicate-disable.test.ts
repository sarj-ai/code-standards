// vitest: shared-module-graph
import rule from "../../src/rules/directive-no-duplicate-disable.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const duplicateRule = (ruleId: string): { messageId: string; data: { ruleId: string } } => ({ messageId: "duplicateRule", data: { ruleId } });

RULE_TESTER.run("directive-no-duplicate-disable", rule, {
  valid: [
    "\n//eslint-disable-line\n",
    "\n/*eslint-disable-line*/\n",
    "\n/*eslint-disable no-undef*/\n//eslint-disable-line no-unused-vars\n//eslint-disable-next-line semi\n/*eslint-disable eqeqeq*/\n",
    "\n/*eslint-disable no-undef*/\n/*eslint-disable-line no-unused-vars*/\n/*eslint-disable-next-line semi*/\n/*eslint-disable eqeqeq*/\n",
    "\n/*oxlint-disable no-undef*/\n/*oxlint-enable no-undef*/\n//eslint-disable-line no-undef\n",
  ],
  invalid: [
    { code: "\n/*eslint-disable*/\n//eslint-disable-line\n", errors: [{ messageId: "duplicate", line: 3, column: 3, endLine: 3, endColumn: 22 }] },
    { code: "\n/*eslint-disable no-undef*/\n//eslint-disable-line no-undef\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 23, endLine: 3, endColumn: 31 }] },
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable-line no-undef*/\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 23, endLine: 3, endColumn: 31 }] },
    { code: "\n/*eslint-disable no-undef*/\n//eslint-disable-next-line no-undef\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 28, endLine: 3, endColumn: 36 }] },
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable-next-line no-undef*/\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 28, endLine: 3, endColumn: 36 }] },
    { code: "\n//eslint-disable-next-line no-undef\n//eslint-disable-line no-undef\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 23, endLine: 3, endColumn: 31 }] },
    { code: "\n/*eslint-disable-next-line no-undef*/\n/*eslint-disable-line no-undef*/\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 23, endLine: 3, endColumn: 31 }] },
    {
      code: "\n// eslint-disable-next-line no-undef -- description\n// eslint-disable-line no-undef -- description\n",
      errors: [{ ...duplicateRule("no-undef"), line: 3, column: 24, endLine: 3, endColumn: 32 }],
    },
    { code: "\n/*oxlint-disable no-undef*/\n//eslint-disable-line no-undef\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 23 }] },
    { code: "\n/*eslint-disable no-undef*/\n//oxlint-disable-next-line no-undef\n", errors: [{ ...duplicateRule("no-undef"), line: 3, column: 28 }] },
    { code: "/*oxlint-disable*/\n/*oxlint-disable no-undef*/", errors: [{ ...duplicateRule("no-undef"), line: 2, column: 18 }] },
  ],
});
