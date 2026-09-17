import { RuleTester } from "@typescript-eslint/rule-tester";
import * as parser from "@typescript-eslint/parser";
import { afterAll, describe, it } from "vitest";
import rule from "../../src/rules/no-conditional-empty-object-spread.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });
TESTER.run("no-conditional-empty-object-spread", rule, {
  valid: [
    "const value = { ...(enabled ? { a: 1 } : { b: 2 }) };",
    "const value = { ...input };",
    "const value = [...(enabled ? [] : items)];",
    "consume(...(enabled ? [] : items));",
    "const value = { ...(enabled && { a: 1 }) };",
    'const value = "...(enabled ? value : {})";',
    "// @generated\nconst value = { ...(enabled ? { a: 1 } : {}) };",
  ],
  invalid: [
    {
      code: "const value = { ...(enabled ? { a: 1 } : {}) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { ...(enabled ? {} : { a: 1 }) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { ...((enabled ? { a: 1 } : {})) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { child: { ...(enabled ? input : {}) } };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
  ],
});
