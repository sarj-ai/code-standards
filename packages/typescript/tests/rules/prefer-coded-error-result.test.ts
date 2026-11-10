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

ruleTester({ lang: "js" }).run(
  "prefer-coded-error-result JavaScript producers",
  rule,
  {
    valid: [
      "import { err } from 'neverthrow'; export const reject = () => err('missing');",
      "import { err } from './domain.js'; export const reject = (name) => err(`Missing ${name}`);",
    ],
    invalid: [
      invalid(
        "import { err } from 'neverthrow'; export const reject = (name) => err(`Missing ${name}`);",
      ),
      invalid(
        "export const reject = (name) => ({ status: 'failed', message: `Missing ${name}` });",
      ),
    ],
  },
);

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
    "export type Outcome<T> = { data: T } | { error: { code: 'duplicate'; name: string } };",
    "export type Outcome<T> = { flag: T } | { error: 'duplicate' | 'denied'; field?: 'name' };",
    "export type Outcome<T> = { value?: T } | { error: string };",
    "export type Outcome<T> = { value: T } | { error?: string };",
    "export type Outcome<T> = { value: T } | { value?: T; error: string };",
    "export type Outcome<T> = { value: T; error?: string } | { error: string };",
    "export type Outcome<T> = { value: T } | { other: T } | { error: string };",
    "export type Outcome = { status: 'pending' } | { error: string };",
    "export type Outcome = { kind: 'ready' } | { error: string };",
    "export type Outcome = { value: string; durationMs: number } | { error: string };",
    "export type Outcome<T> = { value: T } | { error: ValidationError };",
    "export type Outcome<T> = { value: T } | { error: string; code: 'denied' };",
    "export type Outcome = { ok: true; value: number; fallbackError?: string } | { ok: false; fallbackError: string };",
    "export type Outcome = { ok: true; value: number } | { ok: false; fallbackError?: string };",
    "export type Outcome = { ok: true; value: number } | { ok: false; fallbackError: ValidationError };",
    "export type Outcome = { ok: true; value: number } | { ok: false; fallbackError: string; cleanupError: string };",
    "export type Outcome = { ok: true; value: number } | { ok: false; resourceId: string };",
    "export type Outcome = { ok: true; value: number } | { ok: false; error: { code: 'denied' }; errorMessage: string };",
    "export type Outcome = { status: 'loaded'; value: number } | { status: 'failed' | 'unconfigured'; reason: string };",
    "export type Outcome = { state: 'ready'; data: number } | { state: 'error' };",
    "export type Outcome = { kind?: 'success'; data: number } | { kind?: 'failure'; message: string };",
    "export type Outcome = { status: 'pending' } | { status: 'error'; error: string };",
    "export type Outcome = { kind: 'ok'; value: number } | { kind: 'missing'; id: string } | { kind: 'invalid'; field: string };",
    "export type Outcome = { status: 'success'; value: number; error: string } | { status: 'error'; error: string };",
    "export type Outcome = { status: 'success'; value: number } | { status: 'failure'; value?: number; error: string };",
    "export type Outcome = { ok: true; success: false; value: number } | { ok: false; success: true; error: string };",
    "export type Outcome = { ok: true; kind: 'failure'; value: number } | { ok: false; kind: 'success'; error: string };",
    "export type Outcome = { type: 'success'; value: number } | { type: 'failure'; error: { type: 'invalid'; message: string } };",
    `${GENERIC} export type UnknownSuccess = Result<unknown, 'denied'>;`,
    `${GENERIC} export type AnyError = Result<number, any>;`,
    `${GENERIC} export function propagate<Error>(r: Result<number, Error>): Result<number, Error> { return r; }`,
    `${GENERIC} export function propagate<E extends Error>(r: Result<number, E>): Result<number, E> { return r; }`,
    `${GENERIC} import type { Error } from './domain.js'; export type Output = Result<number, Error>;`,
    `${GENERIC} type Error = { code: 'denied' }; export type Output = Result<number, Error>;`,
    `${GENERIC} class Error { code = 'denied'; } export type Output = Result<number, Error>;`,
    `${GENERIC} export type Output = Result<number, DOMException>;`,
    `${GENERIC} export type Output = Result<number, globalThis.Error>;`,
    `${GENERIC} export type Output = Result<number, Error<string>>;`,
    "import { err } from 'neverthrow'; export function reject() { return err('not_found'); }",
    "import { err } from 'neverthrow'; export function reject() { return err('not_' + 'found'); }",
    "import { err } from 'neverthrow'; export function reject() { return err(`not_${'found'}`); }",
    "import { err } from 'neverthrow'; export function reject() { return err('error_' + 404); }",
    "import { err } from 'neverthrow'; const CODE = 'missing'; export function reject() { return err(`${CODE}`); }",
    "import { err } from 'neverthrow'; const PREFIX = 'not_'; const CODE = PREFIX + 'found'; export function reject() { return err(CODE + ''); }",
    "function reject() { return { ok: false, code: 'missing', message: 'Not ' + 'found' }; }",
    "import { err } from 'neverthrow'; export function reject(name: string) { return err({ code: 'duplicate', name }); }",
    "import { errAsync } from 'neverthrow'; export const reject = () => errAsync('not_found');",
    "import { Err } from 'neverthrow'; export const reject = () => new Err('not_found');",
    "import * as nt from 'neverthrow'; export const reject = () => nt.err({ code: 'denied' });",
    "import { err } from './other.js'; export const reject = (name: string) => err(`Missing ${name}`);",
    "function err(message: string) { return message; } export const reject = (name: string) => err(`Missing ${name}`);",
    "import { err } from 'neverthrow'; function reject(err: (s: string) => string, name: string) { return err(`Missing ${name}`); }",
    "import { err } from 'neverthrow'; function reject(name: string) { const alias = err; return alias(`Missing ${name}`); }",
    "import type { err } from 'neverthrow'; export const reject = (name: string) => err(`Missing ${name}`);",
    "import type * as nt from 'neverthrow'; export const reject = (name: string) => nt.err(`Missing ${name}`);",
    "import * as nt from 'neverthrow'; export const reject = (name: string) => nt['err'](`Missing ${name}`);",
    "import { err } from 'neverthrow'; export const reject = (...args: string[]) => err(...args);",
    "import { err } from 'neverthrow'; export const reject = (name: string) => err(`Missing ${name}`).mapErr(() => ({ code: 'missing' }));",
    "import { err } from 'neverthrow'; export function work(name: string) { const local = err(`Missing ${name}`); return local; }",
    "import { err } from 'neverthrow'; export function format(name: string): string { return `Missing ${name}`; }",
    "import { err } from 'neverthrow'; export function reject(error: { code: 'denied' }, name: string) { return err({ error, message: `Denied ${name}` }); }",
    "function reject(error: { code: 'denied' }, name: string) { return { ok: false, fallbackError: error, message: `Denied ${name}` }; }",
    "function reject(name: string) { return { ok: false, fallbackError: `Denied ${name}`, cleanupError: `Cleanup ${name}` }; }",
    "function reject(name: string) { return { ok: false, success: true, code: 'duplicate', message: `Duplicate ${name}` }; }",
    "function reject(name: string) { return { ok: false, value: 1, code: 'partial', message: `Duplicate ${name}` }; }",
    "import * as nt from 'neverthrow'; function reject(nt: { err: (s: string) => string }, name: string) { return nt.err(`Missing ${name}`); }",
    "import { err } from 'neverthrow'; export const reject = (name: string) => err?.(`Missing ${name}`);",
    "import { Err } from 'neverthrow'; export const reject = (name: string) => new Err(`Missing ${name}`, 1);",
    "function reject(name: string) { return { ok: false, code: 'missing', get message() { return `Missing ${name}`; } }; }",
    "function reject(name: string) { return { ok: false, code: 'missing', ['message']: `Missing ${name}` }; }",
    "function reject(name: string) { return { ok: false, code: 'missing', message: `Missing ${name}`, message: 'redacted' }; }",
    "export function fail(): never { throw new Error('Programming defect'); }",
    "export function work(signal: AbortSignal): void { signal.throwIfAborted(); }",
    "export async function work() { try { return await Promise.resolve(1); } catch (error: unknown) { throw error; } }",
    `export type Outcome = { value: number } | ${Array.from({ length: 65 }, () => "{ error: string }").join(" | ")};`,
    `import { err } from 'neverthrow'; export const reject = (name: string) => err(${"'x' + (".repeat(18)}name${")".repeat(18)});`,
  ],
  invalid: [
    ...[
      "export type Outcome<T> = { data: T } | { error: string };",
      "export type Outcome<T> = { flag: T } | { error: string; field?: 'name' };",
      "export type Outcome<T> = { value: T } | { error: unknown };",
      "export type Outcome<T> = Bad | Good<T>; interface Bad { error: string } interface Good<T> { data: T }",
      "type Outcome<T, E> = { value: T } | { error: E }; export type Saved = Outcome<number, string>;",
      "type Outcome<T, E = unknown> = { value: T } | { error: E }; export type Saved = Outcome<number>;",
      "export type Outcome = { ok: true; value: number } | { ok: false; fallbackError: string };",
      "export type Outcome = { ok: true; value: number } | { ok: false; errorMessage: string };",
      "export type Outcome = { ok: true; value: number } | { ok: false; validationError: unknown };",
      "export type Outcome = { ok: true; value: number } | { ok: false; fallbackError: Error };",
      "export type Outcome = { ok: true; data: number } | { ok: false; error: unknown; message: string };",
      "export type Outcome = { status: 'success'; value: number } | { status: 'error'; error: string };",
      "export type Outcome = { kind: 'ok'; value: number } | { kind: 'err'; message: string };",
      "export type Outcome = { type: 'success'; value: number } | { type: 'failure'; reason: string };",
      "export type Outcome = { tag: 'OK'; value: number } | { tag: 'ERROR'; error: string };",
      "type Success = 'success'; type Failed = 'failure'; export type Outcome = { state: Success; value: number } | { state: Failed; error: string };",
      "export type Outcome = { kind: 'ok'; value: number } | { kind: 'error'; message: string };",
      "export type Outcome = { kind: 'ok'; type: 'success'; value: number } | { kind: 'error'; type: 'failure'; message: string };",
      "export type Outcome = { ok: true; value: number } | { ok: false; code: unknown; message: string };",
      "type Code = unknown; export type Outcome = { ok: true; value: number } | { ok: false; code: Code };",
      `${GENERIC} export type Output = Result<number, unknown>;`,
      `${GENERIC} type Opaque = unknown; export type Output = Result<number, Opaque>;`,
      `${GENERIC} export type Output = Result<number, Error>;`,
      `${GENERIC} type Failure = Error; export type Output = Result<number, Failure>;`,
      `${GENERIC} export type Output = Result<number, TypeError>;`,
      `${GENERIC} export type Output = Result<number, AggregateError>;`,
      `${GENERIC} const Error = 1; export type Output = Result<number, Error>;`,
      `${GENERIC} export type Output = Result<number, { code: 'denied' } | unknown>;`,
      "import type * as nt from 'neverthrow'; export type Output = nt.Result<number, string>;",
      "import * as nt from 'neverthrow'; export type Output = nt.ResultAsync<number, unknown>;",
    ].map((code) => invalid(code)),
    ...[
      "import { err } from 'neverthrow'; export const reject = (name: string) => err(`Missing ${name}`);",
      "import { err as fail } from 'neverthrow'; export function reject(name: string) { return fail('Missing ' + name); }",
      "import { errAsync } from 'neverthrow'; export async function reject(name: string) { return await errAsync(`Missing ${name}`); }",
      "import { Err } from 'neverthrow'; export function reject(name: string) { return new Err(`Missing ${name}`); }",
      "import * as nt from 'neverthrow'; export const reject = (name: string) => nt.err(`Missing ${name}`);",
      "import * as nt from 'neverthrow'; export const reject = (name: string) => new nt.Err(`Missing ${name}`);",
      "function reject(name: string) { return { ok: false, message: `Missing ${name}` }; }",
      "function reject(name: string) { return { ok: false, error: `Missing ${name}` }; }",
      "function reject(name: string) { return { kind: 'error', message: `Missing ${name}` }; }",
      "function reject(name: string) { return { kind: 'error', type: 'failure', message: `Missing ${name}` }; }",
      "function reject(name: string) { return { success: false, fallbackError: `Missing ${name}` }; }",
    ].map((code) => invalid(code)),
    ...[
      "import { err } from 'neverthrow'; export const reject = (name: string) => err({ code: 'missing', message: `Missing ${name}` });",
      "import { Err } from 'neverthrow'; export const reject = (name: string) => new Err({ kind: 'missing', reason: 'Missing ' + name });",
      "function reject(name: string) { return { kind: 'error', error: { kind: 'missing', message: `Missing ${name}` } }; }",
      "function reject(name: string) { return { status: 'failed', code: 'missing', message: `Missing ${name}` }; }",
    ].map((code) => ({
      code,
      errors: [{ messageId: "formatAtConsumer" as const }],
      output: null,
    })),
    invalid(
      "import { err, type Result } from 'neverthrow'; export function reject(name: string): Result<number, string> { return err(`Missing ${name}`); }",
    ),
    invalid(
      "type R<T> = { value: T } | { error: string }; export function reject(name: string): R<number> { return { error: `Missing ${name}` }; }",
    ),
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

TESTER.run("prefer-coded-error-result transparent aliases", rule, {
  valid: [
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow';\ntype Wrapper<T, E> = NativeResult<T, E>; export type Output = Wrapper<number, { code: 'denied'; name: string }>;\n",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow';\ntype Wrapper<T, E> = NativeResult<T, E>; export type Output = Wrapper<number, 'denied' | 'missing'>;\n",
    "import type { Result as NativeResult } from './domain.js'; type Wrapper<T,E> = NativeResult<T,E>; export type Output = Wrapper<number,string>;\n",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<E,T> = NativeResult<T,E>; export type O = A<'denied',string>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E='denied'> = NativeResult<T,E>; export type O = A<number>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = Promise<NativeResult<T,E>>; export type O = A<number,{code:'missing';key:string}>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; export function forward<T,E>(value:NativeResult<T,E>):NativeResult<T,E>{return value;}",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,{code:'denied';name:string}|{code:'missing';key:number}>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,'missing'>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,never>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; import type { DomainError } from './domain.js'; type A<T,E> = NativeResult<T,E>; export type O = A<number,DomainError>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type Error = {code:'denied'}; type A<T,E> = NativeResult<T,E>; export type O = A<number,Error>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; export type A<T,E> = NativeResult<T,E>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; export function identity<NativeResult>(value:NativeResult):NativeResult{return value;}",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E>={first:T;second:E}; export type O=A<number,string>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type Promise<T>={value:T}; type A<T,E> = Promise<NativeResult<T,E>>; export type O = A<number,string>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = A<T,E>; export type O=A<number,string>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; import type * as nt from './domain.js'; type A<T,E>=nt.Result<T,E>; export type O=A<number,string>;",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; export type O<T>={status:'loaded';value:T}|{status:'failed'|'unconfigured';reason:string};",
    "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E>=NativeResult<T,E>; export type O=A<number,any>;",
  ],
  invalid: [
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow';\nexport type Output = NativeResult<number, string>;\n",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow';\ntype Wrapper<T, E> = NativeResult<T, E>; export type Output = Wrapper<number, string>;\n",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow';\ntype Wrapper<T, E> = NativeResult<T, E>; export type Output = Wrapper<number, unknown>;\n",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow';\ntype Wrapper<T, E> = NativeAsync<T, E>; export type Output = Wrapper<number, Error>;\n",
      1,
    ),
    invalid(
      "import type * as nt from 'neverthrow'; export type Output = nt.Result<number,string>;\n",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; type B<V,F> = A<V,F>; export type O = B<number,string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<E,T> = NativeResult<T,E>; export type O = A<string,number>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E=string> = NativeResult<T,E>; export type O = A<number>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E=T> = NativeResult<number,E>; export type O = A<string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type E = Error; type A<T,F> = NativeResult<T,F>; export type O = A<number,E>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,'denied'|string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,TypeError|RangeError>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,{code:string;name:string}>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,{code:unknown}>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeResult<T,E>; export type O = A<number,{message:string}>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = NativeAsync<T,E>; export type O = A<number,string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = Promise<NativeResult<T,E>>; export type O = A<number,string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = PromiseLike<NativeResult<T,E>>; export type O = A<number,unknown>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E> = Promise<{ok:true;value:T}|{ok:false;error:E}>; export type O = A<number,string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; type A<T,E>=NativeResult<T,E>; export type O=A<number,string>; export type P=O;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; import type * as nt from 'neverthrow'; type A<T,E>=nt.Result<T,E>; export type O=A<number,string>;",
      1,
    ),
    invalid(
      "import type { Result as NativeResult, ResultAsync as NativeAsync } from 'neverthrow'; import * as nt from 'neverthrow'; type A<T,E>=nt.ResultAsync<T,E>; export type O=A<number,unknown>;",
      1,
    ),
  ],
});

TESTER.run("prefer-coded-error-result conditional producers", rule, {
  valid: [
    "export function save(allowed: boolean, name: string) { return allowed ? { ok: true, value: name } : { ok: false, code: 'denied', name }; }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? null : err('denied'); }",
    "export function save(allowed: boolean, name: string) { return allowed ? name : null; }",
    "export function save(allowed: boolean, name: string) { return allowed ? `Hello ${name}` : `Bye ${name}`; }",
    "export function save(allowed: boolean, name: string) { return allowed ? { status: 'loaded', value: name } : { status: 'unconfigured', reason: `Missing ${name}` }; }",
    "import { err } from './domain.js'; export function save(allowed: boolean, name: string) { return allowed ? null : err(`Denied ${name}`); }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string, err: (s: string) => string) { return allowed ? null : err(`Denied ${name}`); }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? null : err(`Denied ${name}`).mapErr(() => ({code: \"denied\"})); }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; declare function consume(x: unknown): void; export function save(allowed: boolean, name: string) { return allowed ? null : consume(err(`Denied ${name}`)); }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return err(`Denied ${name}`) ? name : null; }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed && err(`Denied ${name}`); }",
    "declare const extra: object; export function save(allowed: boolean, name: string) { return allowed ? null : { ok: false, message: `Denied ${name}`, ...extra }; }",
    "export function save(allowed: boolean, name: string) { return allowed ? null : { ok: false, success: true, message: `Denied ${name}` }; }",
    "export function save(allowed: boolean, name: string) { return allowed ? null : { ok: false, value: name, message: `Denied ${name}` }; }",
    "export function save(allowed: boolean, name: string) { return allowed ? null : { ok: false, fallbackError: `Denied ${name}`, cleanupError: `Cleanup ${name}` }; }",
    "declare const e: {code: 'denied'}; export function save(allowed: boolean, name: string) { return allowed ? null : { ok: false, error: e, message: `Denied ${name}` }; }",
    "import { err, errAsync, Err, type Result } from 'neverthrow'; declare const e: Error; export function save(allowed: boolean, name: string) { return allowed ? null : err(e); }",
    "export function save(allowed: boolean, name: string) { return allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : (allowed ? null : ({ ok: false, message: `Denied ${name}` }))))))))))))))))); }",
    "export function save(allowed: boolean, name: string) { return allowed ? (allowed ? (allowed ? (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })))) : (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))))) : (allowed ? (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })))) : (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })))))) : (allowed ? (allowed ? (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })))) : (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))))) : (allowed ? (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })))) : (allowed ? (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))) : (allowed ? (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` })) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : (allowed ? ({ ok: false, message: `Denied ${name}` }) : ({ ok: false, message: `Denied ${name}` }))))))); }",
  ],
  invalid: [
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? { ok: true, value: name } : err(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? err(`Denied ${name}`) : { ok: true, value: name }; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err as fail } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? fail(`Denied ${name}`) : null; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import * as nt from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? null : nt.err(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? null : new Err(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? null : errAsync(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export async function save(allowed: boolean, name: string) { return await (allowed ? null : errAsync(`Denied ${name}`)); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export async function save(allowed: boolean, name: string) { return allowed ? null : await errAsync(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? null : name ? err(`Denied ${name}`) : null; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? name ? err(`Denied ${name}`) : null : null; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? err(`Denied ${name}`) : err(`Missing ${name}`); }",
      errors: [
        { messageId: "preferCodedErrorResult" },
        { messageId: "preferCodedErrorResult" },
      ],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string) { return allowed ? { ok: false, code: 'denied', message: `Denied ${name}` } : { ok: false, code: 'denied', message: `Denied ${name}` }; }",
      errors: [
        { messageId: "formatAtConsumer" },
        { messageId: "formatAtConsumer" },
      ],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? { ok: false, code: 'denied', message: `Denied ${name}` } : err(`Denied ${name}`); }",
      errors: [
        { messageId: "formatAtConsumer" },
        { messageId: "preferCodedErrorResult" },
      ],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string) { return allowed ? { ok: true, value: name } : { ok: false, message: `Denied ${name}` }; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string) { return allowed ? null : { ok: false, error: { code: 'denied', message: `Denied ${name}` } }; }",
      errors: [{ messageId: "formatAtConsumer" }],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string) { return allowed ? { ok: true, value: name } : { ok: false, code: 'denied', message: `Denied ${name}` }; }",
      errors: [{ messageId: "formatAtConsumer" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export const save = (allowed: boolean, name: string) => allowed ? null : err(`Denied ${name}`);",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "export const service = { save(allowed: boolean, name: string) { return allowed ? null : { ok: false, message: `Denied ${name}` }; } };",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function outer() { return function save(allowed: boolean, name: string) { return allowed ? null : err(`Denied ${name}`); }; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return err(`Denied ${name}`) ? null : err(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string) { return allowed ? null : ({ ok: false, message: `Denied ${name}` } as const); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string) { return allowed ? null : ({ ok: false, message: `Denied ${name}` } satisfies { ok: false; message: string }); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "export function save(allowed: boolean, name: string): { ok: true; value: string } | { ok: false; message: string } { return allowed ? { ok: true, value: name } : { ok: false, message: `Denied ${name}` }; }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string): Result<never, string> { return allowed ? err(\"fixed\") : err(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export async function save(allowed: boolean, name: string): Promise<Result<never, string>> { return allowed ? err(\"fixed\") : err(`Denied ${name}`); }",
      errors: [{ messageId: "preferCodedErrorResult" }],
      output: null,
    },
    {
      code: "import { err, errAsync, Err, type Result } from 'neverthrow'; export function save(allowed: boolean, name: string) { return allowed ? err(`Denied ${name}`) :\n err(`Missing ${name}`); }",
      errors: [
        { messageId: "preferCodedErrorResult" },
        { messageId: "preferCodedErrorResult" },
      ],
      output: null,
    },
  ],
});

function conditionalTree(depth: number): string {
  if (depth === 0) return "{ ok: false, message: `Denied ${name}` }";
  const branch = conditionalTree(depth - 1);
  return `allowed ? (${branch}) : (${branch})`;
}

TESTER.run("prefer-coded-error-result traversal boundaries", rule, {
  valid: [],
  invalid: [
    invalid(
      `export function save(allowed: boolean, name: string) { return ${conditionalTree(6)}; }`,
      64,
    ),
    invalid(
      `export function save(allowed: boolean, name: string) { return ${"allowed ? null : (".repeat(15)}${"{ ok: false, message: `Denied ${name}` }"}${")".repeat(15)}; }`,
    ),
  ],
});
