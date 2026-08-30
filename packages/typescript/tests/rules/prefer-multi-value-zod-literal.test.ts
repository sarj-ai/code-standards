import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";
import rule from "../../src/rules/prefer-multi-value-zod-literal.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});
RULE_TESTER.run("prefer-multi-value-zod-literal", rule, {
  valid: [
    "import { z } from 'zod'; export const V = z.literal([1, 2, 3]);",
    "import { z } from 'zod'; export const V = z.union([z.literal(1), z.string()]);",
    {
      filename: "virtual/schema.ts",
      code: "import { z } from 'zod'; export const V = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
    },
    {
      code: "import { z } from 'zod'; export const V = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
      options: [],
    },
  ],
  invalid: [
    {
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
      errors: [{ messageId: "useMultiValueLiteral" }],
    },
    {
      code: "import { z } from 'zod'; export const V = z.union([z.literal(1), z.literal(2), z.literal(3)]);",
      options: [{ zodMajorVersion: 4 }],
      errors: [{ messageId: "useMultiValueLiteral" }],
    },
  ],
});
