import { RuleTester } from "@typescript-eslint/rule-tester";
import * as parser from "@typescript-eslint/parser";
import { afterAll, describe, it } from "vitest";
import { join } from "node:path";
import rule from "../../src/rules/no-broad-return-type.js";

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
TESTER.run("no-broad-return-type", rule, {
  valid: [
    "function generic<T>(value: Promise<T>): Promise<unknown> { return value; }",
    "function serialize(value: unknown, choose: boolean): unknown { if (choose) return [1]; return value; }",
    "function generic<T extends { id: string }>(value: T): unknown { return value; }",
    "function decode(raw: unknown): unknown { return raw; }",
    "function keep<T>(value: T): unknown { return value; }",
    "function empty(): object { return {}; }",
    "declare function boundary(): unknown;",
    "function exact(value: { id: string }): { id: string } { return value; }",
    "function typed(value: { id: string }) { return value; }",
    'function outer(): unknown { function nested() { return { id: "a" }; } return undefined; }',
    "// @generated\nfunction generated(value: { id: string }): unknown { return value; }",
    "function opaque(value: any): unknown { return value; }",
  ],
  invalid: [
    { name: "preserves the sole named broad return binding", code: "export {}; type Opaque = unknown; function read(value: { id: string }): Opaque { return value; }", output: null, errors: [{ messageId: "avoid" }] },
    { name: "retains broad inference with an independent exported type use", code: "export type Kept = Opaque; type Opaque = unknown; function read(value: { id: string }): Opaque { return value; }", output: "export type Kept = Opaque; type Opaque = unknown; function read(value: { id: string }) { return value; }", errors: [{ messageId: "avoid" }] },
    { name: "does not count a second erasable return annotation as a witness", code: "export {}; type Opaque = unknown; function first(value: { id: string }): Opaque { return value; } function second(value: { id: string }): Opaque { return value; }", output: null, errors: [{ messageId: "avoid" }, { messageId: "avoid" }] },
    { name: "preserves implementation signatures of overload contracts", code: "export {}; function convert(value: true): number; function convert(value: false): string; function convert(value: boolean): unknown { return value ? 1 : 'no'; }", output: null, errors: [{ messageId: "avoid" }] },
    { name: "retains inference only for an unused private module function", code: "export {}; function request(value: { id: string }): unknown { return value; }", output: "export {}; function request(value: { id: string }) { return value; }", errors: [{ messageId: "avoid" }] },
    { name: "preserves an exported alias contract", code: "function request(value: { id: string }): unknown { return value; } export { request };", output: null, errors: [{ messageId: "avoid" }] },
    { name: "preserves a public function contract", code: "export function request(value: { id: string }): unknown { return value; }", output: null, errors: [{ messageId: "avoid" }] },
    { name: "preserves a referenced private function contract", code: "export {}; function request(value: { id: string }): unknown { return value; } request({ id: 'a' });", output: null, errors: [{ messageId: "avoid" }] },
    {
      code: "function request(value: { id: string }): unknown { return value; }",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const request = (value: { id: string }): object => value;",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "type Bag = Record<string, unknown>; function request(value: { id: string }): Bag { return value; }",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "async function request(value: { id: string }): Promise<unknown> { return value; }",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "function request(value: { id: string }): unknown { if (value.id) return value; return null; }",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "class Service { request(value: { id: string }): object { return value; } }",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: 'function request(): Record<string, unknown> { return { id: "a" }; }',
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
  valid: ["function request(value: { id: string }): unknown { return value; }"],
  invalid: [],
});
