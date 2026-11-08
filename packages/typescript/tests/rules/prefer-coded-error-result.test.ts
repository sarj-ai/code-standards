// vitest: shared-module-graph
import rule from "../../src/rules/prefer-coded-error-result.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();
const GENERIC =
  "type Result<T, E> = { ok: true; value: T } | { ok: false; error: E };";
const MESSAGE_ONLY =
  "export type Result<T> = { ok: true; data: T } | { ok: false; message: string };";
const invalid = (code: string, count = 1) => ({
  code,
  errors: Array.from({ length: count }, () => ({
    messageId: "preferCodedErrorResult" as const,
  })),
  output: null,
});

TESTER.run("prefer-coded-error-result", rule, {
  valid: [
    "export function format(name: string): string { return `Denied ${name}`; }",
    "export type Lookup<T> = T | null;",
    "export type Read<T> = { state: 'ready'; data: T } | { state: 'error' };",
    "export type Result<T> = { ok: true; data: T } | { ok: false; error: { code: 'duplicate'; name: string } | { code: 'invalid' } };",
    "export type Result<T> = { ok: true; data: T } | { ok: false; code: 'invalid'; message: string };",
    "export type Result<T> = { ok: true; data: T } | { ok: false; kind: 'invalid'; field: string };",
    "export type Result<T> = { ok: true; data: T } | { ok: false; error: { type: 'invalid'; message: string } };",
    "export type Result<T> = { ok: true; data: T } | { ok: false; tag: 'invalid'; message: string };",
    `${GENERIC} export type Saved = Result<number, 'duplicate' | 'invalid'>;`,
    `${GENERIC} export function forward<T, E>(value: Result<T, E>): Result<T, E> { return value; }`,
    `${GENERIC} export type Parsed = Result<number, ValidationError>;`,
    "import type { Code } from './domain.js'; export type Result = { ok: true; data: number } | { ok: false; code: Code; message: string };",
    "import type { Result } from './unrelated.js'; export type Output = Result<number, string>;",
    "import type { Result } from 'neverthrow'; export type Output = Result<number, 'invalid'>;",
    "import type { Result } from 'neverthrow'; function identity<Result>(value: Result): Result { return value; }",
    "export type Result = { ok?: true; data: number } | { ok?: false; message: string };",
    "export type Result = { ok: boolean; data?: number; message?: string };",
    "export type Partial = { ok: true; data: number; error: string } | { ok: false; error: string };",
    "export type Partial = { ok: true; data: number } | { ok: false; data: number; error: string };",
    "export type Result = { ok: true; data: number } | { ok: false; message?: string };",
    "export type Result = { ok: true; data: number } | { ok: false; error: unknown; message: string };",
    "interface Failed extends Base { ok: false; message: string } export type Result = { ok: true; data: number } | Failed;",
    "interface Failed { ok: false; message: string } interface Failed { code: 'invalid' } export type Result = { ok: true; data: number } | Failed;",
    "export type Result = { ok: true; data: number } | { ok: false; [field: string]: unknown; message: string };",
    "type Text = Text; export type Result = { ok: true; data: number } | { ok: false; message: Text };",
    `${GENERIC} type Recursive = Recursive | Recursive; export type Output = Result<number, Recursive>;`,
    "type Recursive = Recursive | Recursive; export type Output = { ok: true; data: number } | { ok: false; code: Recursive };",
    "type Recursive = Recursive | Recursive; export type Output = Recursive | { ok: false; message: string };",
    "type Other<T, E> = { first: T; second: E }; export type Output = Other<number, string>;",
    {
      filename: "generated.ts",
      code: "// @generated\nexport type Result = { ok: true; data: number } | { ok: false; message: string };",
    },
    "export type Result = { ok: true; data: number } | { ok: false; ['message']: string };",
    "function reject(name: string): { ok: false; code: 'duplicate'; name: string } { return { ok: false, code: 'duplicate', name }; }",
    "function format(name: string) { return `Duplicate ${name}`; }",
    "function reject(name: string) { return { ok: false, code: 'duplicate', message: format(name) }; }",
    "function reject(name: string, extra: object) { return { ok: false, code: 'duplicate', message: `Duplicate ${name}`, ...extra }; }",
    "function reject(name: string, code: string) { return { ok: false, code, message: `Duplicate ${name}` }; }",
    "function reject() { return { ok: false, code: 'duplicate', message: 'Duplicate' }; }",
  ],
  invalid: [
    invalid(
      "export async function reject(name: string): Promise<{ ok: true; data: number } | { ok: false; code: string; message: string }> { return { ok: false, code: 'duplicate', message: `Duplicate ${name}` }; }",
    ),
    invalid(
      "type Weak = { ok: true; data: number } | { ok: false; code: string; message: string }; export async function reject(name: string): Promise<Weak> { return { ok: false, code: 'duplicate', message: `Duplicate ${name}` }; }",
    ),
    {
      code: `${GENERIC} type Weak = { ok: true; data: number } | { ok: false; message: string }; export function reject(name: string): Result<Weak, { code: 'duplicate'; name: string; message: string }> { return { ok: false, error: { code: 'duplicate', name, message: \`Duplicate \${name}\` } }; }`,
      errors: [
        { messageId: "preferCodedErrorResult" },
        { messageId: "formatAtConsumer" },
      ],
      output: null,
    },
    {
      code: MESSAGE_ONLY,
      errors: [
        {
          messageId: "preferCodedErrorResult",
          line: 1,
          column: MESSAGE_ONLY.indexOf("string") + 1,
        },
      ],
      output: null,
    },
    invalid(
      "export type Result<T> = { success: true; data: T } | { success: false; error: string };",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; reason: string };",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; message: 'invalid' | string };",
    ),
    invalid(
      "type Text = string; export type Result = { ok: true; data: number } | { ok: false; message: Text };",
    ),
    invalid(
      "interface Failed { ok: false; message: string } export type Result = { ok: true; data: number } | Failed;",
    ),
    invalid(`${GENERIC} export type Output = Result<number, string>;`),
    invalid(
      `${GENERIC} type Text = string; export type Output = Result<number, Text>;`,
    ),
    invalid(
      `${GENERIC} export async function save(): Promise<Result<number, string>> { return { ok: false, error: 'invalid' }; }`,
    ),
    invalid(
      `${GENERIC} type Wrapped<T> = Result<T, string>; export type Output = Wrapped<number>;`,
    ),
    invalid(
      "type Result<T, E = string> = { ok: true; value: T } | { ok: false; error: E }; export type Output = Result<number>;",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; error: { message: string } };",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; code?: 'invalid'; message: string };",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; code: string; message: string };",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; code: string };",
    ),
    invalid(
      "export type Result = { ok: true; data: number } | { ok: false; code: 'invalid' | string };",
    ),
    invalid(
      "type Code = string | 'invalid'; export type Result = { ok: true; data: number } | { ok: false; code: Code };",
    ),
    invalid(
      `${GENERIC} export type Output = Result<number, string | { code: 'invalid' }>;`,
    ),
    invalid(
      `${GENERIC} type ErrorCode = string | 'invalid'; export type Output = Result<number, ErrorCode>;`,
    ),
    invalid(
      "import type { Result as Outcome } from 'neverthrow'; export type Output = Outcome<number, string>;",
    ),
    invalid(
      "import type { ResultAsync } from 'neverthrow'; export type Output = ResultAsync<number, string>;",
    ),
    invalid(
      "export type Result = { 'ok': true; data: number } | { 'ok': false; 'message': string };",
    ),
    invalid(
      "type Yes = true; type No = false; export type Result = { ok: Yes; data: number } | { ok: No; message: string };",
    ),
    invalid(
      "export type Result = Success | Failure; interface Success { ok: true; data: number } interface Failure { ok: false; message: string }",
    ),
    invalid(
      "export function save(): { ok: true; data: number } | { ok: false; message: string } { return { ok: false, message: 'invalid' }; }",
    ),
    invalid(
      "type Text = string; export type Result = { ok: true; data: number } | { ok: false; message: Text }; export type Again = Result;",
    ),
    ...[
      "function reject(name: string) { return { ok: false, code: 'duplicate', message: `Duplicate ${name}` }; }",
      "const reject = (name: string) => ({ ok: false, code: 'duplicate', message: `Duplicate ${name}` });",
      "function reject(name: string) { return { ok: false, error: { code: 'duplicate', message: `Duplicate ${name}` } }; }",
      "function reject(name: string) { return { success: false, kind: 'duplicate', reason: 'Duplicate ' + name }; }",
      "function reject(name: string) { return { ok: false, code: 'duplicate', name, message: `Duplicate ${name}` }; }",
    ].map((code) => ({
      code,
      errors: [{ messageId: "formatAtConsumer" as const }],
      output: null,
    })),
  ],
});
