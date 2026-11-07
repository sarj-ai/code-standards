// vitest: shared-module-graph
import rule from "../../src/rules/directive-disable-enable-pair.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const missingRulePair = (ruleId: string): { messageId: string; data: { ruleId: string } } => ({ messageId: "missingRulePair", data: { ruleId } });
const WHOLE_FILE = [{ allowWholeFile: true }];

RULE_TESTER.run("directive-disable-enable-pair", rule, {
  valid: [
    "\n/*eslint-disable*/\n/*eslint-enable*/\n",
    "\n/*eslint-disable no-undef,no-unused-vars*/\n/*eslint-enable no-undef,no-unused-vars*/\n",
    "\n/*eslint-disable no-undef,no-unused-vars*/\n/*eslint-enable*/\n",
    "//eslint-disable-line",
    "//eslint-disable-next-line",
    "/*eslint-disable-line*/",
    "/*eslint-disable-next-line*/",
    "/*eslint no-undef: off */",
    "\nfunction foo() {\n    /*eslint-disable*/\n    /*eslint-enable*/\n}\n",
    "\n/*eslint-disable no-undef*/\n/*eslint-disable no-unused-vars*/\n/*eslint-enable*/\n/*eslint-enable*/\n",
    { code: "\nconsole.log('This code does not even have any special comments')\n", options: WHOLE_FILE },
    { code: "\n/*eslint-disable*/\n", options: WHOLE_FILE },
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable no-unused-vars*/\n/*eslint-enable*/\n", options: WHOLE_FILE },
    {
      code: '\n\n/**\n * @file This test case makes sure comments and blank lines\n * before "whole-file" eslint-disable are allowed.\n */\n\n/*eslint-disable*/\n',
      options: WHOLE_FILE,
    },
    { code: "\n/*eslint-disable no-unused-vars, no-undef */\nvar foo = 1\n", options: WHOLE_FILE },
    "\n/*eslint-disable no-undef -- description*/\n/*eslint-enable no-undef*/\n",
    "\n/*eslint-disable no-undef,no-unused-vars -- description*/\n/*eslint-enable no-undef,no-unused-vars*/\n",
    "\n/*oxlint-disable no-undef*/\n/*oxlint-enable no-undef*/\n",
    "\n/*eslint-disable no-undef*/\n/*oxlint-enable no-undef*/\n",
    "\n/*oxlint-disable*/\n/*eslint-enable*/\n",
    { code: "/*oxlint-disable*/\nvar foo = 1", options: WHOLE_FILE },
  ],
  invalid: [
    { code: "\n/*eslint-disable*/\n", errors: [{ messageId: "missingPair", line: 2, column: 3, endLine: 2, endColumn: 17 }] },
    { code: "\n/*eslint-disable no-undef*/\n", errors: [{ ...missingRulePair("no-undef"), line: 2, column: 18, endLine: 2, endColumn: 26 }] },
    { code: "\n/*eslint-disable no-undef,no-unused-vars*/\n/*eslint-enable no-undef*/\n", errors: [{ ...missingRulePair("no-unused-vars"), line: 2, column: 27, endLine: 2, endColumn: 41 }] },
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable no-unused-vars*/\n/*eslint-enable no-unused-vars*/\n", errors: [{ ...missingRulePair("no-undef"), line: 2, column: 18, endLine: 2, endColumn: 26 }] },
    { code: "\n/*eslint-disable no-undef*/\nconsole.log();\n/*eslint-disable no-unused-vars*/\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 4, column: 18, endLine: 4, endColumn: 32 }] },
    { code: "\nconsole.log();\n/*eslint-disable no-unused-vars*/\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 3, column: 18, endLine: 3, endColumn: 32 }] },
    { code: "\n{\n/*eslint-disable no-unused-vars*/\n}\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 3, column: 18, endLine: 3, endColumn: 32 }] },
    { code: "\n{\n/*eslint-disable no-unused-vars -- description */\n}\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 3, column: 18, endLine: 3, endColumn: 32 }] },
    { code: "/* oxlint-disable */\nvar foo = 1", errors: [{ messageId: "missingPair", line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "/* eslint-disable */\nvar foo = 1", options: [{ allowWholeFile: false }], errors: [{ messageId: "missingPair", line: 1, column: 4 }] },
    { code: "var foo = 1;\n// eslint-disable no-undef\n", errors: [missingRulePair("no-undef")] },
    { code: "\n/*oxlint-disable no-undef*/\n/*oxlint-enable no-unused-vars*/\n", errors: [missingRulePair("no-undef")] },
  ],
});
