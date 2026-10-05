import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule from "../../src/rules/no-broad-return-type.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
TESTER.run("no-broad-return-type", rule, {
  valid: [
    "function opaque(value: { id: string }): unknown { return value as unknown; }",
    "import type { Domain } from './domain.js'; function decode(value: Domain): unknown { return value; }",
    "type Record<K, V> = { retained: string }; function decode(value: { id: string }): Record<string, unknown> { return value; }",
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
