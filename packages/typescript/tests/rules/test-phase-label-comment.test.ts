import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { TEST_PHASE_LABEL_COMMENT_DOCUMENTATION } from "../../src/rules/test-phase-label-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("test-phase-label-comment", rule, {
  valid: [
    { code: TEST_PHASE_LABEL_COMMENT_DOCUMENTATION.examples[0].files[0].source, filename: "widget.test.ts" },
    { code: "// Arrange\nconst widget = makeWidget();", filename: "widget.ts" },
    { code: "const values = [\n  // Arrange\n  arrangeValue,\n];", filename: "widget.test.ts" },
    { code: "const value = run(); // Act", filename: "widget.test.ts" },
    { code: "// Actor\nexpect(run()).toBe(true);", filename: "widget.test.ts" },
    { code: "// Then a retry would duplicate the charge.\nexpect(run()).toBe(true);", filename: "widget.test.ts" },
    { code: "// Arrange / Act / Assert the result\nexpect(run()).toBe(true);", filename: "widget.test.ts" },
    { code: "// Given / When / Therefore\nexpect(run()).toBe(true);", filename: "widget.test.ts" },
    {
      code: "// Duplicate keys would silently delete an\n// assertion.\nexpect(run()).toBe(true);",
      filename: "widget.test.ts",
    },
    { code: `// ${"-".repeat(41)} Arrange\nexpect(run()).toBe(true);`, filename: "widget.test.ts" },
    { code: "/* Arrange */\nexpect(run()).toBe(true);", filename: "widget.test.ts" },
    { code: "// Setup\nconst widget = makeWidget();", filename: "widget.test.ts" },
    { code: "// @generated\n// Arrange\nconst widget = makeWidget();", filename: "widget.test.ts" },
  ],
  invalid: [
    {
      code: TEST_PHASE_LABEL_COMMENT_DOCUMENTATION.examples[1].files[0].source,
      filename: "widget.test.ts",
      output: "const widget = makeWidget();",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "function test() {\r\n\t// Given / When / Then\r\n\texpect(run()).toBe(true);\r\n}",
      filename: "tests/widget.ts",
      output: "function test() {\r\n\texpect(run()).toBe(true);\r\n}",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "// Assertions\nexpect(run()).toBe(true);",
      filename: "widget.test.ts",
      output: "expect(run()).toBe(true);",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "// ~~~ Verification ~~~\nexpect(run()).toBe(true);",
      filename: "widget.test.ts",
      output: "expect(run()).toBe(true);",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "// Prepare, Execute, Verify, Cleanup\nexpect(run()).toBe(true);",
      filename: "widget.test.ts",
      output: "expect(run()).toBe(true);",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "// Arrange and Act and Assert\nexpect(run()).toBe(true);",
      filename: "widget.test.ts",
      output: "expect(run()).toBe(true);",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "// Act -> Assert\nexpect(run()).toBe(true);",
      filename: "widget.test.ts",
      output: "expect(run()).toBe(true);",
      errors: [{ messageId: "removeLabel" }],
    },
    {
      code: "// Given\nconst input = makeInput();\n// When\nconst result = run(input);\n// Then\nexpect(result).toBe(true);",
      filename: "widget.test.ts",
      output: "const input = makeInput();\nconst result = run(input);\nexpect(result).toBe(true);",
      errors: [
        { messageId: "removeLabel" },
        { messageId: "removeLabel" },
        { messageId: "removeLabel" },
      ],
    },
  ],
});
