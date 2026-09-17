import { RuleTester } from "@typescript-eslint/rule-tester";
import * as parser from "@typescript-eslint/parser";
import { afterAll, describe, it } from "vitest";
import { join } from "node:path";
import rule from "../../src/rules/prefer-typed-reflection.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({
  languageOptions: {
    parser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});
TESTER.run("prefer-typed-reflection", rule, {
  valid: [
    'function read(Reflect: { get(target: object, key: string): unknown }, target: object) { return Reflect.get(target, "id"); }',
    'declare const target: Record<string, unknown>; Reflect.get(target, "id");',
    "declare const target: { id: string }; declare const key: string; Reflect.get(target, key);",
    'declare const target: { id: string }; Reflect.get(target, "id", other);',
    'declare const target: any; Reflect.get(target, "id");',
    "declare const args: unknown[]; function run(n: number) {} Reflect.apply(run, undefined, args);",
    '// @generated\ndeclare const target: { id: string }; Reflect.get(target, "id");',
    'function read<T extends object>(target: T) { return Reflect.get(target, "id"); }',
    'Reflect.ownKeys({ id: "a" });',
  ],
  invalid: [
    {
      code: 'declare const target: { id: string }; Reflect.get(target, "id");',
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'declare const target: { id: string }; Reflect["get"](target, "missing");',
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "function send(id: string) {} Reflect.apply(send, undefined, [42]);",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'function send(id: string) {} globalThis.Reflect.apply(send, undefined, ["a"]);',
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'declare const target: { id: string }; globalThis.Reflect.get(target, "id");',
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
  ],
});
const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("without type information", rule, {
  valid: ['declare const target: { id: string }; Reflect.get(target, "id");'],
  invalid: [],
});
