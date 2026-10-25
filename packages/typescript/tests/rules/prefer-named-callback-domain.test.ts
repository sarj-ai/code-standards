// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";
import rule from "../../src/rules/prefer-named-callback-domain.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});
RULE_TESTER.run("prefer-named-callback-domain", rule, {
  valid: [
    {
      name: "ignores a private local alias inside an exported function",
      code: "export function run() { type Local = (value: 'a' | 'b') => void; const callback: Local = () => {}; callback('a'); }",
    },
    {
      name: "ignores a local interface in an exported class method",
      code: "export class Service { run() { interface Local { callback: (value: 'a' | 'b') => void } } }",
    },
    "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: Boundary) => void; }",
    "interface Local { done?: (boundary: 'seeded' | 'queued') => void; }",
    {
      filename: "src/options.test.ts",
      code: "export interface Options { done: (boundary: 'a' | 'b') => void }",
    },
  ],
  invalid: [
    {
      name: "preserves unresolved ownership boundary 1",
      code: "type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
      output: null,
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      name: "preserves unresolved ownership boundary 2",
      code: "export type Boundary = 'seeded' | 'queued'; export type Other = 'seeded' | 'queued'; export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
      output: null,
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      name: "preserves unresolved ownership boundary 3",
      code: "export type Boundary = 'seeded' | 'queued'; export interface Options<Boundary> { done?: (boundary: 'seeded' | 'queued') => void; }",
      output: null,
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      name: "preserves unresolved ownership boundary 4",
      code: "export type Boundary = 'seeded' | 'queued' | 'other'; export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
      output: null,
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      name: "preserves unresolved ownership boundary 5",
      code: "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: 'seeded' /* domain */ | 'queued') => void; }",
      output: null,
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      name: "reuses the unique existing exported alias",
      code: "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
      output:
        "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: Boundary) => void; }",
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      code: "export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }",
      errors: [{ messageId: "nameCallbackDomain" }],
    },
    {
      code: "export type Options = { done: ((boundary: 'seeded' | 'queued') => void) | undefined };",
      errors: [{ messageId: "nameCallbackDomain" }],
    },
  ],
});
