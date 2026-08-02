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
    {
      name: "allows independent all-boolean flag sets",
      code: "interface StateDependencies { data?: boolean; error?: boolean; isValidating?: boolean; isLoading?: boolean }",
    },
    {
      name: "allows an explicit discriminated union",
      code: "type Result = { ok: true; data: string } | { ok: false; error: string };",
    },
    {
      name: "allows an interface with only one optional payload",
      code: "interface Result { success: boolean; data?: string; }",
    },
    {
      name: "allows a type literal with only one optional payload",
      code: "type Result = { success: boolean; data?: string };",
    },
    {
      name: "allows status flags without optional members",
      code: "interface Flags { ok: boolean; failed: boolean; }",
    },
    {
      name: "allows interfaces without a recognized status member",
      code: "interface Config { host?: string; port?: number; timeout?: number; }",
    },
    {
      name: "allows type literals without a recognized status member",
      code: "type Config = { host?: string; port?: number; timeout?: number };",
    },
    {
      name: "allows a non-boolean member named success",
      code: "interface Response { success: string; data?: string; error?: string; }",
    },
    {
      name: "allows an unrelated boolean member",
      code: "interface Thing { enabled: boolean; data?: string; meta?: number; }",
    },
    {
      name: "allows an optional-only object type",
      code: "type Opts = { a?: number; b?: number; c?: number };",
    },
    {
      name: "allows an empty interface",
      code: "interface Empty {}",
    },
    {
      name: "allows a non-object type alias",
      code: 'type Status = "ok" | "error";',
    },
  ],
  invalid: [
    {
      name: "rejects a status flag with optional payloads",
      code: "interface Result { success: boolean; data?: string; error?: Error }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an interface with success and two optional payloads",
      code: "interface Result { success: boolean; data?: string; error?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects a type literal with ok and two optional payloads",
      code: "type Result = { ok: boolean; data?: string; error?: string };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "recognizes error as a status member",
      code: "interface ApiResponse { error: boolean; payload?: unknown; message?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "recognizes failed as a status member",
      code: "type Job = { failed: boolean; result?: string; reason?: string; code?: number };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "recognizes isError as a status member",
      code: "interface State { isError: boolean; value?: number; cause?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects more than two optional members",
      code: "interface Outcome { ok: boolean; data?: string; error?: string; warning?: string; retryable?: boolean; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "recognizes a string-literal status key",
      code: 'type Result = { "success": boolean; data?: string; error?: string };',
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects one payload mixed with optional boolean flags",
      code: "interface Result { success: boolean; data?: string; stale?: boolean; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
  ],
});
