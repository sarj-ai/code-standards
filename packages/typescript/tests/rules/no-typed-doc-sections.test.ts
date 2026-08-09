import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  noTypedDocSectionsDocumentation,
} from "../../src/rules/no-typed-doc-sections.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("no-typed-doc-sections", rule, {
  valid: [
    {
      name: "preserves behavioral documentation",
      code: noTypedDocSectionsDocumentation.examples[0].files[0].source,
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
    {
      name: "flags a description-free parameter tag",
      code: "/** @param id */\nexport function fetchValue(id: string): number { return 1; }",
      errors: [{ messageId: "typedSection" }],
    },
    {
      name: "flags a parameter description that only expands its name",
      code: "/** @param userId the user identifier */\nexport function fetchValue(userId: string): number { return 1; }",
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
      code: noTypedDocSectionsDocumentation.examples[1].files[0].source,
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
