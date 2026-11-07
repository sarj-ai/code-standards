/** @fileoverview no-numeric-search-param-coercion — the documentation and executable examples of `@sarj/no-numeric-search-param-coercion`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_NUMERIC_SEARCH_PARAM_COERCION_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Parse numeric URL search parameters with a schema instead of parseInt or Number.",
  rationale:
    "parseInt, parseFloat and Number accept a missing or malformed query value and return NaN or a truncated number (`parseInt(\"10abc\")` is 10), which then reaches queries and pagination unchecked.",
  remediation:
    "Parse the value with a schema that states the contract, for example `z.coerce.number().int().positive().default(10).parse(params.get(\"page\") ?? undefined)`.",
  category: "correctness",
  limitations: [
    "Requires type information: only the `get` result of a value typed as URLSearchParams or ReadonlyURLSearchParams is recognized.",
    "Search parameter objects passed as page props, values copied into other variables, and unary `+` coercion are not followed.",
  ],
  examples: [
    {
      id: "schema-parsed-page",
      title: "Parse the page number with a schema",
      outcome: "no-match",
      files: [{
        path: "src/page.ts",
        source:
          "declare const z: { coerce: { number(): { parse(value: unknown): number } } };\n" +
          "export function page(params: URLSearchParams): number {\n  return z.coerce.number().parse(params.get(\"page\") ?? undefined);\n}\n",
      }],
      focusPath: "src/page.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "parse-int-page",
      title: "Do not coerce a search parameter with parseInt",
      outcome: "match",
      files: [{
        path: "src/page.ts",
        source: "export function page(params: URLSearchParams): number {\n  return parseInt(params.get(\"page\") ?? \"1\", 10);\n}\n",
      }],
      focusPath: "src/page.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
