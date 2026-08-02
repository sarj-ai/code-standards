import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-typed-doc-sections.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("no-typed-doc-sections", rule, {
  valid: [
    "/** Retry because the vendor may return 429. */\nexport function fetchValue(id: string): number { return 1; }",
    "/** @param id external identifier */\nexport function fetchValue(id) { return 1; }",
    "/** @example fetchValue('abc') */\nexport function fetchValue(id: string): number { return 1; }",
  ],
  invalid: [
    {
      code: "/** @param id external identifier\n * @returns the value\n */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @returns the value */\nexport const fetchValue = (id: string): number => 1;",
      errors: [{ messageId: "typedSection" }],
    },
  ],
});
