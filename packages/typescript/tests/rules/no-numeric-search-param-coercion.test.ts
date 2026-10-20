import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/no-numeric-search-param-coercion.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

const READONLY_PARAMS = "declare class ReadonlyURLSearchParams { get(name: string): string | null }\n";

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

RULE_TESTER.run("no-numeric-search-param-coercion", rule, {
  valid: [
    {
      code: "declare const params: URLSearchParams; const page = Number(params.get('page') ?? '1');",
      filename: "route.test.ts",
    },
    "declare const params: URLSearchParams; const page = params.get('page');",
    "declare const params: Map<string, string>; const page = parseInt(params.get('page') ?? '1', 10);",
    "declare const params: URLSearchParams; const parseInt = (value: string | null) => 1; parseInt(params.get('page'));",
    "declare const params: URLSearchParams; const page = parseInt(String(params.size), 10);",
    "declare const params: URLSearchParams; const raw = params.get('page'); const page = Number(raw);",
    "declare const params: URLSearchParams; const page = String(params.get('page'));",
  ],
  invalid: [
    {
      code: "declare const params: URLSearchParams; const page = Number(params.get('page'));",
      errors: [{ messageId: "noNumericSearchParamCoercion", data: { parser: "Number" } }],
    },
    {
      code: "declare const params: URLSearchParams; const page = Number.parseInt(params.get('page')!, 10);",
      errors: [{ messageId: "noNumericSearchParamCoercion", data: { parser: "Number.parseInt" } }],
    },
    {
      code: "declare const params: URLSearchParams | undefined; const size = parseFloat(params?.get('size') ?? '');",
      errors: [{ messageId: "noNumericSearchParamCoercion", data: { parser: "parseFloat" } }],
    },
    {
      code: `${READONLY_PARAMS}declare const params: ReadonlyURLSearchParams; const page = parseInt(params.get('page') as string, 10);`,
      errors: [{ messageId: "noNumericSearchParamCoercion", data: { parser: "parseInt" } }],
    },
    {
      code: "declare const url: URL; const page = parseInt(url.searchParams.get('page') ?? '1', 10);",
      errors: [{ messageId: "noNumericSearchParamCoercion", data: { parser: "parseInt" } }],
    },
  ],
});
