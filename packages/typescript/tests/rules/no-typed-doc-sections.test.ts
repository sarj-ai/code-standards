import { RuleTester } from "@typescript-eslint/rule-tester";
import * as tsParser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule, {
  NO_TYPED_DOC_SECTIONS_DOCUMENTATION,
} from "../../src/rules/no-typed-doc-sections.js";
import restatedJsdoc from "../../src/rules/no-restated-jsdoc.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

it.each([
  "/** @param value مطلوب */\nfunction f(value: string): void {}",
  "/** @param [value=ready] */\nfunction f(value: string): void {}",
  "/** @param missing */\nfunction f(value: string): void {}",
  "/** @returns 'string' */\nfunction f(): string { return 'string'; }",
])("preserves a contract with both JSDoc rules enabled: %s", (source) => {
  const findings = new Linter().verify(source, [{
    files: ["**/*.ts"],
    languageOptions: { parser: tsParser },
    plugins: { sarj: { rules: { typed: rule, restated: restatedJsdoc } } },
    rules: { "sarj/typed": "warn", "sarj/restated": "warn" },
  }], { filename: "src/contracts.ts" });
  expect(findings).toEqual([]);
});

new RuleTester().run("no-typed-doc-sections", rule, {
  valid: [
    { name: "preserves explicit types that differ from the signature", code: "/** @param value {unused}\n * @returns {string}\n */\nfunction f(value: number): number { return value; }" },
    { name: "preserves a narrower explicit parameter type", code: "/** @param {string} value */\nfunction f(value: unknown): void {}" },
    { name: "preserves optional parameter defaults", code: "/** @param [value=ready] */\nfunction f(value: string): void {}" },
    { name: "preserves nested parameter documentation", code: "/** @param options.value */\nfunction f(options: { value: string }): void {}" },
    { name: "requires the documented parameter to exist", code: "/** @param missing */\nfunction f(value: string): void {}" },
    { name: "associates the comment with the adjacent overload only", code: "/** @param value */\nfunction f(name: string): void;\nfunction f(value: number): void;\nfunction f(value: string | number): void {}" },
    { name: "does not borrow an outer function signature", code: "function outer(value: string): void {\n/** @param value */\nconst x = 1;\n}" },
    { name: "preserves a previous statement's trailing comment", code: "const x = 1; /** @param value */\nfunction f(value: string): void {}" },
    { name: "preserves quoted return values", code: "/** @returns 'string' */\nfunction f(): string { return 'string'; }" },
    { name: "preserves arithmetic parameter contracts", code: "/** @param value -value */\nfunction f(value: number): void {}" },
    { name: "preserves Unicode parameter meaning", code: "/** @param value مطلوب */\nfunction f(value: string): void {}" },
    { name: "preserves numeric return contracts", code: "/** @returns 0 */\nfunction f(): number { return 0; }" },
    { name: "preserves parameter comparisons", code: "/** @param value <= value */\nfunction f(value: number): void {}" },
    { name: "preserves malformed parameter payloads", code: "/** @param ??? */\nfunction f(value: number): void {}" },
    {
      name: "preserves behavioral documentation",
      code: NO_TYPED_DOC_SECTIONS_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "preserves documented side effects",
      code: "/** Writes the successful lookup to the audit log. */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "preserves documented invariants",
      code: "/** The returned value is monotonic within a session. */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "preserves external contract links",
      code: "/** @see https://vendor.example/contracts/value */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "preserves examples",
      code: "/** @example fetchValue('abc') */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "preserves deprecation guidance",
      code: "/** @deprecated Use fetchCurrentValue instead. */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "preserves failure semantics",
      code: "/** @throws {VendorError} when the vendor rejects the request */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "permits parameter tags when the parameter is untyped",
      code: "/** @param id external identifier */\nexport function fetchValue(id) { return 1; }",
    },
    {
      name: "permits return tags when the return is inferred",
      code: "/** @returns the value */\nexport function fetchValue(id: string) { return 1; }",
    },
    {
      name: "permits return tags when a parameter is untyped",
      code: "/** @returns the value */\nexport function fetchValue(id): number { return 1; }",
    },
    {
      name: "preserves parameter value mappings",
      code: "/** @param weekStart - The day the week starts on (0 = Sunday, 1 = Monday, etc.) */\nexport function startOfWeek(weekStart: number): Date { return new Date(); }",
    },
    {
      name: "preserves semantic return meaning",
      code: "/** @returns Whether the feature is enabled for the team. */\nexport function hasFeature(teamId: string): boolean { return true; }",
    },
    {
      name: "preserves units absent from the parameter name",
      code: "/** @param timeout - Maximum wait in milliseconds before aborting. */\nexport function poll(timeout: number): boolean { return true; }",
    },
    {
      name: "preserves novel parameter context",
      code: "/** @param id external identifier */\nexport function fetchValue(id: string): number { return 1; }",
    },
    {
      name: "preserves novel parameter context alongside failure semantics",
      code: "/** @param id external identifier\n * @throws {VendorError} when the vendor rejects the request\n */\nexport function fetchValue(id: string): number { return 1; }",
    },
  ],
  invalid: [
    { name: "reports an exact primitive parameter type repetition", code: "/** @param {string} value */\nfunction f(value: string): void {}", errors: [{ messageId: "typedSection" }] },
    {
      name: "flags a description-free parameter tag",
      code: "/** @param id */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      name: "flags a parameter description that only expands its name",
      code: NO_TYPED_DOC_SECTIONS_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "typedSection" }],
    },
    {
      name: "flags a type-only return tag",
      code: "/** @returns {boolean} */\nexport function fetchValue(id: string): boolean { return true; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      name: "flags one vacuous tag while preserving the meaningful tag",
      code: "/** @param id the identifier\n * @returns Whether the feature is enabled.\n */\nexport function fetchValue(id: string): boolean { return true; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @param id external identifier\n * @returns the value\n */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @returns the value */\nexport const fetchValue = (id: string): number => 1;",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @argument id external identifier\n * @return the value\n */\nexport default function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "class Client {\n  /** @arg id external identifier\n   * @yield the value\n   */\n  *fetchValue(id: string): Generator<number> { yield 1; }\n}",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @param id the identifier */\ndeclare function fetchValue(id: string): number;",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @param id the identifier\n * @throws {VendorError} when the vendor rejects the request\n */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @returns the value\n * @example fetchValue('abc')\n */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
  ],
});
