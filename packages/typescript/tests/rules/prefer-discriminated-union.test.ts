import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-discriminated-union.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("prefer-discriminated-union", rule, {
  valid: [
    // FP guard, corpus: swr/src/_internal/types.ts:1191 — an all-boolean record
    // is a FLAG SET; every combination is legal, so there is no illegal state.
    {
      code: "interface StateDependencies { data?: boolean; error?: boolean; isValidating?: boolean; isLoading?: boolean }",
    },
    // A proper discriminated union — the prescribed pattern.
    {
      code: "type Result = { ok: true; data: string } | { ok: false; error: string };",
    },
    // Status boolean but fewer than 2 optionals (only 1 optional).
    {
      code: "interface Result { success: boolean; data?: string; }",
    },
    {
      code: "type Result = { success: boolean; data?: string };",
    },
    // Status boolean with no optionals at all.
    {
      code: "interface Flags { ok: boolean; failed: boolean; }",
    },
    // >= 2 optionals but NO status boolean member.
    {
      code: "interface Config { host?: string; port?: number; timeout?: number; }",
    },
    {
      code: "type Config = { host?: string; port?: number; timeout?: number };",
    },
    // Has a member named `success` but it is NOT boolean-typed; plus optionals.
    {
      code: "interface Response { success: string; data?: string; error?: string; }",
    },
    // 2 optionals but the boolean is named something non-status.
    {
      code: "interface Thing { enabled: boolean; data?: string; meta?: number; }",
    },
    // Plain object type with optionals, no status boolean.
    {
      code: "type Opts = { a?: number; b?: number; c?: number };",
    },
    // Empty interface — nothing to flag.
    {
      code: "interface Empty {}",
    },
    // Type alias to a non-object type — not an object type literal.
    {
      code: 'type Status = "ok" | "error";',
    },
  ],
  invalid: [
    // A boolean flag alongside an actual optional PAYLOAD still fires.
    {
      code: "interface Result { success: boolean; data?: string; error?: Error }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // interface form: `success` boolean + 2 optionals.
    {
      code: "interface Result { success: boolean; data?: string; error?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // type-alias form: `ok` boolean + 2 optionals.
    {
      code: "type Result = { ok: boolean; data?: string; error?: string };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // `error` as the boolean status member + 2 optionals.
    {
      code: "interface ApiResponse { error: boolean; payload?: unknown; message?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // `failed` status member + 3 optionals.
    {
      code: "type Job = { failed: boolean; result?: string; reason?: string; code?: number };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // `isError` status member + 2 optionals.
    {
      code: "interface State { isError: boolean; value?: number; cause?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // More than 2 optionals alongside the status boolean.
    {
      code: "interface Outcome { ok: boolean; data?: string; error?: string; warning?: string; retryable?: boolean; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    // String-literal key for the status boolean still counts.
    {
      code: 'type Result = { "success": boolean; data?: string; error?: string };',
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
  ],
});
