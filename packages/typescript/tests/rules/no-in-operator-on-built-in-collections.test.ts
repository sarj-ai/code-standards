import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule, {
  NO_IN_OPERATOR_ON_BUILT_IN_COLLECTIONS_DOCUMENTATION as DOC,
} from "../../src/rules/no-in-operator-on-built-in-collections.js";
RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const source = (code: string) => ({ code, filename: "src/example.ts" });
const error = { messageId: "ambiguousCollectionIn" };
tester.run("@sarj/no-in-operator-on-built-in-collections", rule, {
  valid: [
    source(
      DOC.examples.find((example) => example.outcome === "no-match")!.files[0]
        .source,
    ),
    ...[
      'const value = {}; "id" in value;',
      'class Map {} const cache = new Map(); "id" in cache;',
      'import {Map} from "./domain"; const cache = new Map(); "id" in cache;',
      'let cache = new Map(); cache = {}; "id" in cache;',
      'const cache = new Map(); function check(cache:object){return "id" in cache}',
      'declare const cache: Map<string,object> | {id:string}; "id" in cache;',
      'const cache = importedCache; "id" in cache;',
      '// @generated\nconst cache=new Map(); "id" in cache;',
    ].map(source),
  ],
  invalid: [
    source(
      DOC.examples.find((example) => example.outcome === "match")!.files[0]
        .source,
    ),
    ...[
      'const cache=new Map(); "id" in cache;',
      'declare const cache: ReadonlyMap<string,object>; "id" in cache;',
      'const cache=new Set(); const alias=cache; "id" in alias;',
      'function check(cache:WeakSet<object>){return "id" in cache}',
      '"id" in new WeakMap();',
    ].map(source),
  ].map((test) => ({ ...test, errors: [error] })),
});
