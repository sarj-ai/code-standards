import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule, {
  NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION as DOC,
} from "../../src/rules/no-json-stringify-object-equality.js";
RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const source = (code: string) => ({ code, filename: "src/example.ts" });
const error = { messageId: "serializedObjectEquality" };
tester.run("@sarj/no-json-stringify-object-equality", rule, {
  valid: [
    source(
      DOC.examples.find((example) => example.outcome === "no-match")!.files[0]
        .source,
    ),
    ...[
      'JSON.stringify([1,true,"x",null]) === JSON.stringify([1,true,"x",null]);',
      "JSON.stringify(1) === JSON.stringify(2);",
      'JSON.stringify(actual) === "expected";',
      "const JSON=custom; JSON.stringify(actual)===JSON.stringify(expected);",
      "function run(JSON){return JSON.stringify(actual)===JSON.stringify(expected)}",
      "const serializer=JSON.stringify; serializer(a)===serializer(b);",
      "const before=JSON.stringify(a); before===JSON.stringify(b);",
      "// @generated\nJSON.stringify(a)===JSON.stringify(b);",
    ].map(source),
    {
      code: "JSON.stringify(a)===JSON.stringify(b)",
      filename: "src/compare.test.ts",
    },
  ],
  invalid: [
    source(
      DOC.examples.find((example) => example.outcome === "match")!.files[0]
        .source,
    ),
    ...[
      "JSON.stringify({id:1}) === JSON.stringify({id:1});",
      'JSON["stringify"](a) !== JSON["stringify"](b);',
      "JSON.stringify([{}]) == JSON.stringify([]);",
    ].map(source),
  ].map((test) => ({ ...test, errors: [error] })),
});
