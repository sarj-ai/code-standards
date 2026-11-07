import rule from "../../src/rules/no-numeric-search-param-coercion.js";
import { FIXTURES, RuleTester, ruleTester, typed } from "./_tester.js";

const RULE_TESTER = ruleTester({ cwd: FIXTURES });

const READONLY_PARAMS = "declare class ReadonlyURLSearchParams { get(name: string): string | null }\n";

const SCHEMA_PARSED_PAGE_EXAMPLE =
  "declare const z: { coerce: { number(): { parse(value: unknown): number } } };\n" +
  "export function page(params: URLSearchParams): number {\n  return z.coerce.number().parse(params.get(\"page\") ?? undefined);\n}\n";
const PARSE_INT_PAGE_EXAMPLE = "export function page(params: URLSearchParams): number {\n  return parseInt(params.get(\"page\") ?? \"1\", 10);\n}\n";

new RuleTester({ eslintCompat: true, languageOptions: { parserOptions: { lang: "ts" } } }).run("no-numeric-search-param-coercion without type information", rule, {
  valid: [{ name: "reports nothing without types, as the original does without a program", code: PARSE_INT_PAGE_EXAMPLE, settings: { sarj: { typeAware: false } } }],
  invalid: [],
});

RULE_TESTER.run("no-numeric-search-param-coercion", rule, typed({
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
    { name: "schema-parsed-page", code: SCHEMA_PARSED_PAGE_EXAMPLE, filename: "src/page.ts" },
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
    { name: "parse-int-page", code: PARSE_INT_PAGE_EXAMPLE, filename: "src/page.ts", errors: [{ messageId: "noNumericSearchParamCoercion" }] },
  ],
}));
