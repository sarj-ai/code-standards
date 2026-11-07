// vitest: shared-module-graph
import rule from "../../src/rules/directive-no-aggregating-enable.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const aggregating = (count: number): { messageId: string; data: { count: string } } => ({ messageId: "aggregatingEnable", data: { count: String(count) } });

RULE_TESTER.run("directive-no-aggregating-enable", rule, {
  valid: [
    "\n            /*eslint-disable no-redeclare*/\n            /*eslint-enable no-redeclare*/\n        ",
    "\n            /*eslint-disable no-redeclare*/\n            /*eslint-enable no-shadow*/\n        ",
    "\n            /*eslint-disable no-redeclare, no-shadow*/\n            /*eslint-enable*/\n        ",
    "\n            /*eslint-disable no-redeclare, no-shadow*/\n            /*eslint-enable no-redeclare, no-shadow*/\n        ",
    "\n            /*eslint-disable no-redeclare, no-shadow*/\n            /*eslint-enable no-redeclare*/\n            /*eslint-enable no-shadow*/\n        ",
    "\n/*oxlint-disable no-redeclare*/\n/*eslint-enable no-redeclare*/\n",
  ],
  invalid: [
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-enable*/\n            ",
      errors: [{ ...aggregating(2), line: 4, column: 19, endLine: 4, endColumn: 32 }],
    },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-disable no-undef*/\n                /*eslint-enable*/\n            ",
      errors: [aggregating(3)],
    },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-enable no-redeclare, no-shadow*/\n            ",
      errors: [aggregating(2)],
    },
    {
      code: "\n                /*eslint-disable no-redeclare*/\n                /*eslint-disable no-shadow*/\n                /*eslint-enable -- description*/\n            ",
      errors: [aggregating(2)],
    },
    { code: "/*oxlint-disable no-redeclare*/\n/*eslint-disable no-shadow*/\n/*oxlint-enable*/", errors: [{ ...aggregating(2), line: 3, column: 3 }] },
  ],
});
