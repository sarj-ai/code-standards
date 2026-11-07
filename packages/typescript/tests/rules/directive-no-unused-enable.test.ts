// vitest: shared-module-graph
import rule from "../../src/rules/directive-no-unused-enable.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const unusedRule = (ruleId: string): { messageId: string; data: { ruleId: string } } => ({ messageId: "unusedRule", data: { ruleId } });

RULE_TESTER.run("directive-no-unused-enable", rule, {
  valid: [
    "\n/*eslint no-undef:error*/\n/*eslint-disable*/\nvar a = b\n/*eslint-enable*/\n",
    "\n/*eslint no-undef:error*/\n/*eslint-disable no-undef*/\nvar a = b\n/*eslint-enable no-undef*/\n",
    "\n/*eslint no-undef:error*/\n/*eslint-disable no-undef*/\nvar a = b\n/*eslint-enable*/\n",
    "\n/*eslint no-undef:error, no-unused-vars:error*/\n/*eslint-disable no-undef,no-unused-vars*/\nvar a = b\n/*eslint-enable no-undef*/\n",
    "\n/*eslint no-undef:error, no-unused-vars:error*/\n/*eslint-disable no-undef,no-unused-vars*/\nvar a = b\n/*eslint-enable*/\n",
    "\n/*oxlint-disable no-undef*/\nvar a = b\n/*eslint-enable no-undef*/\n",
    "\n/*eslint-disable*/\nvar a = b\n/*oxlint-enable*/\n",
  ],
  invalid: [
    { code: "/*eslint-enable*/", errors: [{ messageId: "unused", line: 1, column: 3, endLine: 1, endColumn: 16 }] },
    { code: "/*eslint-enable no-undef*/", errors: [{ ...unusedRule("no-undef"), line: 1, column: 17, endLine: 1, endColumn: 25 }] },
    { code: "\n/*eslint-disable no-unused-vars*/\n/*eslint-enable no-undef*/\n", errors: [{ ...unusedRule("no-undef"), line: 3, column: 17, endLine: 3, endColumn: 25 }] },
    { code: "/*eslint-enable -- description*/", errors: [{ messageId: "unused", line: 1, column: 3, endLine: 1, endColumn: 16 }] },
    { code: "/*oxlint-enable*/", errors: [{ messageId: "unused", line: 1, column: 3 }] },
    { code: "\n/*oxlint-disable no-unused-vars*/\n/*oxlint-enable no-undef*/\n", errors: [{ ...unusedRule("no-undef"), line: 3, column: 17 }] },
    { code: "\n// eslint-enable no-undef\n", errors: [unusedRule("no-undef")] },
  ],
});
