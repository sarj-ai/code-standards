import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule, {
  PREFER_TYPED_REFLECTION_DOCUMENTATION as DOC,
} from "../../src/rules/prefer-typed-reflection.js";
RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const source = (code: string) => ({ code, filename: "src/example.ts" });
const error = { messageId: "avoid" };
tester.run("@sarj/prefer-typed-reflection", rule, {
  valid: [
    source(
      DOC.examples.find((example) => example.outcome === "no-match")!.files[0]
        .source,
    ),
    ...[
      'function readType(value: object): unknown { return Reflect.get(value, "type"); }',
      'declare const value: unknown; Reflect.get(value, "type");',
      'declare const value: any; Reflect.get(value, "type");',
      'declare const value: {}; Reflect.get(value, "type");',
      'type Boundary = object; function readType(value: Boundary): unknown { return Reflect.get(value, "type"); }',
      'type Boundary = object; function readType(value: Boundary = read()): unknown { return Reflect.get(value, "type"); }',
      'Reflect.get(value as object, "type");',
      'Reflect.get((value as object)!, "type");',
      'type Boundary = object; type Alias = Readonly<Boundary>; function readType(value: Alias): unknown { return Reflect.get(value, "type"); }',
      'const Reflect = custom; Reflect.get(target, "id");',
      "function run(Reflect){return Reflect.apply(target,null,[])}",
      "Reflect.get(target,key);",
      'Reflect.get(target,"id",receiver);',
      "Reflect.apply(target,null,args);",
      'const reflection=Reflect; reflection.get(target,"id");',
      'const globalThis={Reflect:custom}; globalThis.Reflect.get(target,"id");',
      '// @generated\nReflect.get(target,"id");',
    ].map(source),
  ],
  invalid: [
    source(
      DOC.examples.find((example) => example.outcome === "match")!.files[0]
        .source,
    ),
    ...[
      'function readType(value: { type: string }): unknown { return Reflect.get(value, "type"); }',
      'type Boundary = { type: string }; function readType(value: Boundary): unknown { return Reflect.get(value, "type"); }',
      'type Boundary = object; function readType() { type Boundary = { type: string }; const value: Boundary = read(); return Reflect.get(value, "type"); }',
      'Reflect.get(target,"id");',
      'Reflect["get"](target,1);',
      'globalThis.Reflect.get(target,"id");',
      "Reflect.apply(fn,undefined,[1]);",
    ].map(source),
  ].map((test) => ({ ...test, errors: [error] })),
});
