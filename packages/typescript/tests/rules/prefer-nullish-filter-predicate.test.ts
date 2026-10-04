import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule, {
  PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION as DOC,
} from "../../src/rules/prefer-nullish-filter-predicate.js";
RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const source = (code: string) => ({ code, filename: "src/example.ts" });
const error = { messageId: "preferNullishPredicate" };
tester.run("@sarj/prefer-nullish-filter-predicate", rule, {
  valid: [
    source("const values=[null,{}]; values.push(0); values.filter(Boolean);"),
    source(
      "const values=[null,{}]; const alias=values; alias.push(0); values.filter(Boolean);",
    ),
    source(
      "const values=[null,{}]; unknownConsumer(values); values.filter(Boolean);",
    ),

    source(
      DOC.examples.find((example) => example.outcome === "no-match")!.files[0]
        .source,
    ),
    ...[
      "declare const values: readonly (string|null)[]; values.filter(Boolean);",
      "declare const values: (0|{id:string}|null)[]; values.filter(Boolean);",
      "declare const values: (unknown|null)[]; values.filter(Boolean);",
      "function run(Boolean){return [null,{}].filter(Boolean)}",
      "const values=[null,{}]; function run(values){return values.filter(Boolean)}",
      "let values=[null,{}]; values=[0]; values.filter(Boolean);",
      "const values=imported; values.filter(Boolean);",
      "[null,{}].filter(value=>value!==null);",
      "// @generated\n[null,{}].filter(Boolean);",
    ].map(source),
  ],
  invalid: [
    source(
      DOC.examples.find((example) => example.outcome === "match")!.files[0]
        .source,
    ),
    ...[
      "[null,{}].filter(Boolean);",
      "declare const values: readonly ({id:string}|null)[]; values.filter(Boolean);",
      "const values=[null,{}]; const alias=values; alias.filter(Boolean);",
      "declare const values: (true|null|undefined)[]; values.filter(Boolean);",
    ].map(source),
  ].map((test) => ({
    ...test,
    errors: [
      {
        ...error,
        suggestions: [
          {
            messageId: "replaceBoolean",
            output: test.code.replace(
              "filter(Boolean)",
              "filter((value) => value !== null && value !== undefined)",
            ),
          },
        ],
      },
    ],
  })),
});
