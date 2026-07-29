import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/strict-test-assertions.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("strict-test-assertions", rule, {
  valid: [
    {
      code: `expect(obj).toMatchObject({ a: 1, b: 2 });`,
    },
    {
      code: `expect(obj.a).toBe(1);`,
    },
    {
      code: `
        expect(obj1.a).toBe(1);
        expect(obj2.b).toBe(2);
      `,
    },
  ],
  invalid: [
    {
      code: `
        expect(obj.a).toBe(1);
        expect(obj.b).toBe(2);
      `,
      output: `
        expect(obj).toMatchObject({ a: 1, b: 2 });
        
      `,
      errors: [{ messageId: "combineAssertions" }],
    },
  ],
});
