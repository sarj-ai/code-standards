import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";
import rule from "../../src/rules/prefer-named-callback-domain.js";

RuleTester.afterAll = afterAll; RuleTester.describe = describe; RuleTester.it = it; RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { ecmaVersion: "latest", sourceType: "module" } } });
RULE_TESTER.run("prefer-named-callback-domain", rule, {
  valid: [
    "export type Boundary = 'seeded' | 'queued'; export interface Options { done?: (boundary: Boundary) => void; }",
    "interface Local { done?: (boundary: 'seeded' | 'queued') => void; }",
    { filename: "src/options.test.ts", code: "export interface Options { done: (boundary: 'a' | 'b') => void }" },
  ],
  invalid: [{ code: "export interface Options { done?: (boundary: 'seeded' | 'queued') => void; }", errors: [{ messageId: "nameCallbackDomain" }] },
    { code: "export type Options = { done: ((boundary: 'seeded' | 'queued') => void) | undefined };", errors: [{ messageId: "nameCallbackDomain" }] }],
});
