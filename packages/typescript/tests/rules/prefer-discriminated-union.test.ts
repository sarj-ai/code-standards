import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferDiscriminatedUnionDocumentation } from "../../src/rules/prefer-discriminated-union.js";

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
    { name: "public no-match example", filename: preferDiscriminatedUnionDocumentation.examples[0].focusPath, code: preferDiscriminatedUnionDocumentation.examples[0].files[0].source },
    {
      name: "allows independent all-boolean flag sets",
      code: "interface StateDependencies { data?: boolean; error?: boolean; isValidating?: boolean; isLoading?: boolean }",
    },
    {
      name: "allows an explicit discriminated union",
      code: "type Result = { ok: true; data: string } | { ok: false; error: string };",
    },
    {
      name: "allows an exclusive-property result narrowed with in",
      code: [
        "type Result<T> = { data: T } | { error: string };",
        "declare const result: Result<string>;",
        'if ("error" in result) console.error(result.error);',
      ].join("\n"),
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
      name: "allows an optional status in partial wire data",
      code: "interface PartialResponse { ok?: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows a negative boolean without a positive result discriminant",
      code: "interface State { isError: boolean; value?: number; cause?: string; }",
    },
    {
      name: "allows independent optional payloads without a failure branch",
      code: "interface TeamResponse { ok: boolean; teamId?: string; url?: string; }",
    },
    {
      name: "allows a failure field when the record also carries independent metadata",
      code: "interface OperationState { success: boolean; errors?: Error[]; requestId: string; }",
    },
    {
      name: "allows aggregate response metadata despite an optional error",
      code: "interface Page { ok: boolean; items?: Item[]; page?: number; error?: string; }",
    },
    {
      name: "takes a false negative for domain-specific branch names",
      code: "interface BookingResult { success: boolean; bookingId?: string; reason?: string; }",
    },
    {
      name: "allows inherited object shapes whose full state is not local",
      code: "interface Result extends Metadata { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows generated declarations",
      filename: "/repo/generated/api.ts",
      code: "interface Result { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows declaration files",
      filename: "/repo/api.d.ts",
      code: "interface Result { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows test fixtures",
      filename: "/repo/result.test.ts",
      code: "interface Result { ok: boolean; data?: string; error?: string; }",
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
    {
      name: "allows a named result in a Promise return annotation",
      code: "declare function load(): Promise<Result>;",
    },
    {
      name: "allows an inline return union whose full state is not local",
      code: "declare function load(): { ok: boolean; data?: string; error?: string } | undefined;",
    },
    {
      name: "allows an inline return intersection whose full state is not local",
      code: "declare function load(): Metadata & { ok: boolean; data?: string; error?: string };",
    },
    {
      name: "allows a Promise whose object argument is a union constituent",
      code: "declare function load(): Promise<{ ok: boolean; data?: string; error?: string } | undefined>;",
    },
    {
      name: "allows an inline parameter shape because the function does not produce it",
      code: "declare function consume(value: { ok: boolean; data?: string; error?: string }): void;",
    },
    {
      name: "allows an inline variable annotation",
      code: "declare const result: { ok: boolean; data?: string; error?: string };",
    },
    {
      name: "allows PromiseLike return annotations outside the exact Promise boundary",
      code: "declare function load(): PromiseLike<{ ok: boolean; data?: string; error?: string }>;",
    },
    {
      name: "allows inline return shapes in test fixtures",
      filename: "/repo/result.test.ts",
      code: "declare function load(): Promise<{ ok: boolean; data?: string; error?: string }> ;",
    },
  ],
  invalid: [
    { name: "public match example", filename: preferDiscriminatedUnionDocumentation.examples[1].focusPath, code: preferDiscriminatedUnionDocumentation.examples[1].files[0].source, errors: [{ messageId: "preferDiscriminatedUnion" }] },
    {
      name: "rejects a direct inline function return shape",
      code: "declare function load(): { ok: boolean; data?: string; error?: string };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an inline Promise return shape",
      code: "declare function load(): Promise<{ ok: boolean; data?: string; error?: string }> ;",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an arrow function inline Promise return shape",
      code: "const load = async (): Promise<{ success: boolean; result?: string; reason?: Error }> => null as never;",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an inline method return shape",
      code: "class Loader { load(): { ok: boolean; value?: string; cause?: Error } { return null as never; } }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an inline function-type return shape",
      code: "type Loader = () => { ok: boolean; payload?: string; errors?: Error[] };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
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
      name: "rejects a success flag with booking and failure branches",
      code: "interface BookingResult { success: boolean; result?: Booking; reason?: string; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an exact success-or-errors interface",
      code: "interface ValidationResult { success: boolean; errors?: ZodIssue[]; }",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an exact ok-or-error type alias",
      code: "type ParseResult = { ok: boolean; error?: string };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
    {
      name: "rejects an exact success-or-reason inline return",
      code: "declare function validate(): { success: boolean; reason?: string };",
      errors: [{ messageId: "preferDiscriminatedUnion" }],
    },
  ],
});
