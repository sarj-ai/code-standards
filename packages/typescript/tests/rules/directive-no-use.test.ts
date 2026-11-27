// vitest: shared-module-graph
import rule from "../../src/rules/directive-no-use.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const ALL = ["eslint", "eslint-env", "eslint-enable", "eslint-disable", "eslint-disable-line", "eslint-disable-next-line", "exported", "global", "globals"];
const disallow = (kind: string): { messageId: string; data: { kind: string } } => ({ messageId: "disallow", data: { kind } });
const missingRulePair = (ruleId: string): { messageId: string; data: { ruleId: string } } => ({ messageId: "missingRulePair", data: { ruleId } });
const WHOLE_FILE = [{ allowWholeFile: true, allow: ALL }];
const aggregating = (count: number): { messageId: string; data: { count: string } } => ({ messageId: "aggregatingEnable", data: { count: String(count) } });
const unusedRule = (ruleId: string): { messageId: string; data: { ruleId: string } } => ({ messageId: "unusedRule", data: { ruleId } });

RULE_TESTER.run("directive-no-use", rule, {
  valid: [
    "// eslint foo",
    "// exported",
    "// global",
    "// globals",
    "// eslint-env",
    "/* just eslint in a normal comment */",
    { code: "/* eslint */", options: [{ allow: ["eslint"] }] },
    { code: "/* eslint-env */", options: [{ allow: ["eslint-env"] }] },
    { code: "// eslint-disable-line", options: [{ allow: ["eslint-disable-line"] }] },
    { code: "// eslint-disable-next-line", options: [{ allow: ["eslint-disable-next-line"] }] },
    { code: "/* eslint-disable-line */", options: [{ allow: ["eslint-disable-line"] }] },
    { code: "/* eslint-disable-next-line */", options: [{ allow: ["eslint-disable-next-line"] }] },
    { code: "/* exported */", options: [{ allow: ["exported"] }] },
    { code: "/* global */", options: [{ allow: ["global"] }] },
    { code: "/* globals */", options: [{ allow: ["globals"] }] },
    { code: "// oxlint-disable-next-line", options: [{ allow: ["eslint-disable-next-line"] }] },
    { code: "foo(); // oxlint-disable-line eqeqeq", options: [{ allow: ["eslint-disable-line"] }] },
    { code: "/* oxlint-disable */\n/* oxlint-enable */", options: [{ allow: ["eslint-disable", "eslint-enable"] }] },
  ],
  invalid: [
    { code: "/* eslint-enable */", options: [{ allow: ["eslint-enable"] }], errors: [{ messageId: "unused", line: 1, column: 4, endLine: 1, endColumn: 17 }] },
    { code: "/* eslint-disable */", options: [{ allow: ["eslint-disable"] }], errors: [{ messageId: "missingPair", line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "/* eslint */", errors: [disallow("eslint")] },
    { code: "/* eslint-env */", errors: [disallow("eslint-env")] },
    { code: "/* eslint-enable */", errors: [disallow("eslint-enable"), { messageId: "unused", line: 1, column: 4, endLine: 1, endColumn: 17 }] },
    { code: "/* eslint-disable */", errors: [{ ...disallow("eslint-disable"), line: 1, column: 4, endLine: 1, endColumn: 18 }, { messageId: "missingPair", line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "// eslint-disable-line", errors: [disallow("eslint-disable-line")] },
    { code: "// eslint-disable-next-line", errors: [disallow("eslint-disable-next-line")] },
    { code: "/* eslint-disable-line */", errors: [disallow("eslint-disable-line")] },
    { code: "/* eslint-disable-next-line */", errors: [disallow("eslint-disable-next-line")] },
    { code: "/* exported */", errors: [disallow("exported")] },
    { code: "/* global */", errors: [disallow("global")] },
    { code: "/* globals */", errors: [disallow("globals")] },
    { code: "/* eslint-disable */", options: [{ allow: ["globals"] }], errors: [disallow("eslint-disable"), { messageId: "missingPair", line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "// eslint-disable", errors: [disallow("eslint-disable"), { messageId: "missingPair", line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "// eslint-enable", errors: [disallow("eslint-enable"), { messageId: "unused", line: 1, column: 4, endLine: 1, endColumn: 17 }] },
    { code: "/* oxlint-disable no-console */", options: [{ allow: ["eslint-disable-next-line"] }], errors: [disallow("oxlint-disable"), { messageId: "missingRulePair", data: { ruleId: "no-console" }, line: 1, column: 19, endLine: 1, endColumn: 29 }] },
    { code: "// oxlint-enable", errors: [disallow("oxlint-enable"), { messageId: "unused", line: 1, column: 4, endLine: 1, endColumn: 17 }] },
    { code: "// oxlint-disable-next-line", options: [{ allow: ["oxlint-disable-next-line"] }], errors: [disallow("oxlint-disable-next-line")] },
    { code: "/* eslint-disable no-console -- cli */\nconsole.log(1);\n", options: [{ allow: ["eslint-disable-line", "eslint-disable-next-line", "eslint-env", "exported", "global", "globals"], allowWholeFile: false }], errors: [disallow("eslint-disable"), missingRulePair("no-console")] },
    { code: "/* eslint-enable */", options: [{ allowWholeFile: true, allow: ["eslint-enable"] }], errors: [{ messageId: "unused" }] },
  ],
});

RULE_TESTER.run("directive-no-use (directive-disable-enable-pair)", rule, {
  valid: [
    { code: "\n/*eslint-disable*/\n/*eslint-enable*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint-disable no-undef,no-unused-vars*/\n/*eslint-enable no-undef,no-unused-vars*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint-disable no-undef,no-unused-vars*/\n/*eslint-enable*/\n", options: [{ allow: ALL }] },
    { code: "//eslint-disable-line", options: [{ allow: ALL }] },
    { code: "//eslint-disable-next-line", options: [{ allow: ALL }] },
    { code: "/*eslint-disable-line*/", options: [{ allow: ALL }] },
    { code: "/*eslint-disable-next-line*/", options: [{ allow: ALL }] },
    { code: "/*eslint no-undef: off */", options: [{ allow: ALL }] },
    { code: "\nfunction foo() {\n    /*eslint-disable*/\n    /*eslint-enable*/\n}\n", options: [{ allow: ALL }] },
    { code: "\nconsole.log('This code does not even have any special comments')\n", options: WHOLE_FILE },
    { code: "\n/*eslint-disable*/\n", options: WHOLE_FILE },
    {
      code: '\n\n/**\n * @file This test case makes sure comments and blank lines\n * before "whole-file" eslint-disable are allowed.\n */\n\n/*eslint-disable*/\n',
      options: WHOLE_FILE,
    },
    { code: "\n/*eslint-disable no-unused-vars, no-undef */\nvar foo = 1\n", options: WHOLE_FILE },
    { code: "\n/*eslint-disable no-undef -- description*/\n/*eslint-enable no-undef*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint-disable no-undef,no-unused-vars -- description*/\n/*eslint-enable no-undef,no-unused-vars*/\n", options: [{ allow: ALL }] },
    { code: "\n/*oxlint-disable no-undef*/\n/*oxlint-enable no-undef*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint-disable no-undef*/\n/*oxlint-enable no-undef*/\n", options: [{ allow: ALL }] },
    { code: "\n/*oxlint-disable*/\n/*eslint-enable*/\n", options: [{ allow: ALL }] },
    { code: "/*oxlint-disable*/\nvar foo = 1", options: WHOLE_FILE },
  ],
  invalid: [
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable no-unused-vars*/\n/*eslint-enable*/\n/*eslint-enable*/\n", options: [{ allow: ALL }], errors: [{ messageId: "aggregatingEnable", data: { count: "2" }, line: 4, column: 3, endLine: 4, endColumn: 16 }, { messageId: "unused", line: 5, column: 3, endLine: 5, endColumn: 16 }] },
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable no-unused-vars*/\n/*eslint-enable*/\n", options: WHOLE_FILE, errors: [{ messageId: "aggregatingEnable", data: { count: "2" }, line: 4, column: 3, endLine: 4, endColumn: 16 }] },
    { code: "\n/*eslint-disable*/\n", options: [{ allow: ALL }], errors: [{ messageId: "missingPair", line: 2, column: 3, endLine: 2, endColumn: 17 }] },
    { code: "\n/*eslint-disable no-undef*/\n", options: [{ allow: ALL }], errors: [{ ...missingRulePair("no-undef"), line: 2, column: 18, endLine: 2, endColumn: 26 }] },
    { code: "\n/*eslint-disable no-undef,no-unused-vars*/\n/*eslint-enable no-undef*/\n", options: [{ allow: ALL }], errors: [{ ...missingRulePair("no-unused-vars"), line: 2, column: 27, endLine: 2, endColumn: 41 }] },
    { code: "\n/*eslint-disable no-undef*/\n/*eslint-disable no-unused-vars*/\n/*eslint-enable no-unused-vars*/\n", options: [{ allow: ALL }], errors: [{ ...missingRulePair("no-undef"), line: 2, column: 18, endLine: 2, endColumn: 26 }] },
    { code: "\n/*eslint-disable no-undef*/\nconsole.log();\n/*eslint-disable no-unused-vars*/\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 4, column: 18, endLine: 4, endColumn: 32 }] },
    { code: "\nconsole.log();\n/*eslint-disable no-unused-vars*/\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 3, column: 18, endLine: 3, endColumn: 32 }] },
    { code: "\n{\n/*eslint-disable no-unused-vars*/\n}\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 3, column: 18, endLine: 3, endColumn: 32 }] },
    { code: "\n{\n/*eslint-disable no-unused-vars -- description */\n}\n", options: WHOLE_FILE, errors: [{ ...missingRulePair("no-unused-vars"), line: 3, column: 18, endLine: 3, endColumn: 32 }] },
    { code: "/* oxlint-disable */\nvar foo = 1", options: [{ allow: ALL }], errors: [{ messageId: "missingPair", line: 1, column: 4, endLine: 1, endColumn: 18 }] },
    { code: "/* eslint-disable */\nvar foo = 1", options: [{ allowWholeFile: false, allow: ALL }], errors: [{ messageId: "missingPair", line: 1, column: 4 }] },
    { code: "var foo = 1;\n// eslint-disable no-undef\n", options: [{ allow: ALL }], errors: [missingRulePair("no-undef")] },
    { code: "\n/*oxlint-disable no-undef*/\n/*oxlint-enable no-unused-vars*/\n", options: [{ allow: ALL }], errors: [missingRulePair("no-undef"), { messageId: "unusedRule", data: { ruleId: "no-unused-vars" }, line: 3, column: 17, endLine: 3, endColumn: 31 }] },
  ],
});

RULE_TESTER.run("directive-no-use (directive-no-aggregating-enable)", rule, {
  valid: [
    { code: "\n            /*eslint-disable no-redeclare*/\n            /*eslint-enable no-redeclare*/\n        ", options: [{ allow: ALL }] },
    { code: "\n            /*eslint-disable no-redeclare, no-shadow*/\n            /*eslint-enable*/\n        ", options: [{ allow: ALL }] },
    { code: "\n            /*eslint-disable no-redeclare, no-shadow*/\n            /*eslint-enable no-redeclare, no-shadow*/\n        ", options: [{ allow: ALL }] },
    { code: "\n            /*eslint-disable no-redeclare, no-shadow*/\n            /*eslint-enable no-redeclare*/\n            /*eslint-enable no-shadow*/\n        ", options: [{ allow: ALL }] },
    { code: "\n/*oxlint-disable no-redeclare*/\n/*eslint-enable no-redeclare*/\n", options: [{ allow: ALL }] },
  ],
  invalid: [
    { code: "\n            /*eslint-disable no-redeclare*/\n            /*eslint-enable no-shadow*/\n        ", options: [{ allow: ALL }], errors: [{ messageId: "missingRulePair", data: { ruleId: "no-redeclare" }, line: 2, column: 30, endLine: 2, endColumn: 42 }, { messageId: "unusedRule", data: { ruleId: "no-shadow" }, line: 3, column: 29, endLine: 3, endColumn: 38 }] },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-enable*/\n            ", options: [{ allow: ALL }],
      errors: [{ ...aggregating(2), line: 4, column: 19, endLine: 4, endColumn: 32 }],
    },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-disable no-undef*/\n                /*eslint-enable*/\n            ", options: [{ allow: ALL }],
      errors: [aggregating(3)],
    },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-enable no-redeclare, no-shadow*/\n            ", options: [{ allow: ALL }],
      errors: [aggregating(2)],
    },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-enable -- description*/\n            ", options: [{ allow: ALL }],
      errors: [aggregating(2)],
    },
    { code: "/*oxlint-disable no-redeclare*/\n/*eslint-disable no-shadow*/\n/*oxlint-enable*/", options: [{ allow: ALL }], errors: [{ ...aggregating(2), line: 3, column: 3 }] },
  ],
});

RULE_TESTER.run("directive-no-use (directive-no-unused-enable)", rule, {
  valid: [
    { code: "\n/*eslint no-undef:error*/\n/*eslint-disable*/\nvar a = b\n/*eslint-enable*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint no-undef:error*/\n/*eslint-disable no-undef*/\nvar a = b\n/*eslint-enable no-undef*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint no-undef:error*/\n/*eslint-disable no-undef*/\nvar a = b\n/*eslint-enable*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint no-undef:error, no-unused-vars:error*/\n/*eslint-disable no-undef,no-unused-vars*/\nvar a = b\n/*eslint-enable*/\n", options: [{ allow: ALL }] },
    { code: "\n/*oxlint-disable no-undef*/\nvar a = b\n/*eslint-enable no-undef*/\n", options: [{ allow: ALL }] },
    { code: "\n/*eslint-disable*/\nvar a = b\n/*oxlint-enable*/\n", options: [{ allow: ALL }] },
  ],
  invalid: [
    { code: "\n/*eslint no-undef:error, no-unused-vars:error*/\n/*eslint-disable no-undef,no-unused-vars*/\nvar a = b\n/*eslint-enable no-undef*/\n", options: [{ allow: ALL }], errors: [{ messageId: "missingRulePair", data: { ruleId: "no-unused-vars" }, line: 3, column: 27, endLine: 3, endColumn: 41 }] },
    { code: "/*eslint-enable*/", options: [{ allow: ALL }], errors: [{ messageId: "unused", line: 1, column: 3, endLine: 1, endColumn: 16 }] },
    { code: "/*eslint-enable no-undef*/", options: [{ allow: ALL }], errors: [{ ...unusedRule("no-undef"), line: 1, column: 17, endLine: 1, endColumn: 25 }] },
    { code: "\n/*eslint-disable no-unused-vars*/\n/*eslint-enable no-undef*/\n", options: [{ allow: ALL }], errors: [{ messageId: "missingRulePair", data: { ruleId: "no-unused-vars" }, line: 2, column: 18, endLine: 2, endColumn: 32 }, { ...unusedRule("no-undef"), line: 3, column: 17, endLine: 3, endColumn: 25 }] },
    { code: "/*eslint-enable -- description*/", options: [{ allow: ALL }], errors: [{ messageId: "unused", line: 1, column: 3, endLine: 1, endColumn: 16 }] },
    { code: "/*oxlint-enable*/", options: [{ allow: ALL }], errors: [{ messageId: "unused", line: 1, column: 3 }] },
    { code: "\n/*oxlint-disable no-unused-vars*/\n/*oxlint-enable no-undef*/\n", options: [{ allow: ALL }], errors: [{ messageId: "missingRulePair", data: { ruleId: "no-unused-vars" }, line: 2, column: 18, endLine: 2, endColumn: 32 }, { ...unusedRule("no-undef"), line: 3, column: 17 }] },
    { code: "\n// eslint-enable no-undef\n", options: [{ allow: ALL }], errors: [unusedRule("no-undef")] },
  ],
});
