import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION } from "../../src/rules/prefer-named-complex-return-type.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("prefer-named-complex-return-type", rule, {
  valid: [
    PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION.examples[0].files[0].source,
    "function small(): { id: string; name: string } { return { id: '', name: '' }; }",
    "function inferred() { return { id: '', name: '', active: true }; }",
    "function primitives(): 'a' | 'b' | 'c' { return 'a'; }",
    { filename: "src/job.test.ts", code: "function fixture(): { a: 1; b: 2; c: 3 } { return { a: 1, b: 2, c: 3 }; }" },
    { filename: "src/generated/job.ts", code: "function generated(): { a: 1; b: 2; c: 3 } { return { a: 1, b: 2, c: 3 }; }" },
  ],
  invalid: [
    {
      code: PREFER_NAMED_COMPLEX_RETURN_TYPE_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      code: "declare function load(): Promise<{ id: string; name: string; active: boolean }>;;",
      errors: [{ messageId: "nameComplexReturnType" }],
    },
    {
      code: "interface Port { load(): { id: string; name: string; active: boolean } }",
      errors: [{ messageId: "nameComplexReturnType" }],
    },
  ],
});
