import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-non-nullable-collection.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

ruleTester.run("prefer-non-nullable-collection", rule, {
  valid: [
    "interface Input { organizationIds: OrganizationId[]; }",
    "type Response = { items: Array<string> };",
    "interface Input { value: string | string[] | null; }",
    "interface Input { id: string | null; }",
    "interface Input { ids?: string[]; }",
    "function search(ids: string[] | null): Item[] | undefined { return undefined; }",
    "type Result = Promise<Item[] | null>;",
    "type MaybeItem = Item | null;",
    {
      code: "interface Input { ids: string[] | null; }",
      filename: "src/search.test.ts",
    },
    {
      code: "interface Input { ids: string[] | null; }",
      filename: "src/generated/api.ts",
    },
    {
      code: "interface Input { ids: string[] | null; }",
      filename: "src/vendor/api.ts",
    },
  ],
  invalid: [
    {
      code: "interface Input { organizationIds: OrganizationId[] | null; }",
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      code: "type Response = { items: null | string[] | undefined };",
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      code: "class State { statuses!: Array<Status> | undefined; }",
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      code: "interface Input { ids: string[] | ReadonlyArray<string> | null; }",
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
    {
      code: "type MaybeItems = Item[] | null;",
      errors: [{ messageId: "preferNonNullableCollection" }],
    },
  ],
});
