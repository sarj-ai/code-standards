import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-typed-doc-sections.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("no-typed-doc-sections", rule, {
  valid: [
    {
      name: "preserves behavioral documentation",
      code: "/** Retries when the vendor returns 429. */\nexport function fetchValue(id: string): number { return 1; }",
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
  ],
  invalid: [
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
      code: "/** @param id external identifier */\ndeclare function fetchValue(id: string): number;",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @param id external identifier\n * @throws {VendorError} when the vendor rejects the request\n */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      code: "/** @returns the value\n * @example fetchValue('abc')\n */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
  ],
});
