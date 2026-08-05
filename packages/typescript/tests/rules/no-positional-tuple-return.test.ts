import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-positional-tuple-return.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-positional-tuple-return", rule, {
  valid: [
    // --- The named form, which is the whole point. ---
    {
      code: "export function download(): { body: string; contentType: string | null } { return impl(); }",
    },
    // --- Not exported: the call sites live in this file. ---
    {
      code: "function split(): [string, number] { return impl(); }",
    },
    {
      name: "keeps detached export matching scoped to the exported binding",
      code: "function split(): [string, number] { return impl(); }\nconst other = 1;\nexport { other };",
    },
    // A same-named binding exported from ANOTHER module is not this function.
    {
      code: "function split(): [string, number] { return impl(); }\nexport { split } from './other.js';",
    },
    // A type-only export does not put the value on the public surface.
    {
      code: "function split(): [string, number] { return impl(); }\nexport type { split };",
    },
    {
      code: "function split(): [string, number] { return impl(); }\nexport { type split };",
    },
    // --- Single-element tuple and array types are not positional records. ---
    { code: "export function one(): [string] { return impl(); }" },
    { code: "export function many(): Array<[string, number]> { return impl(); }" },
    // --- No return annotation to judge. ---
    { code: "export function inferred() { return ['a', 1]; }" },
  ],
  invalid: [
    {
      name: "rejects a homogeneous fixed tuple",
      code: "export function bounds(): [number, number] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a variadic tuple boundary",
      code: "export function args(): [string, ...number[]] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects labeled tuple members because their runtime representation is still positional",
      code: "export function respond(): [status: number, body: string] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a tagged tuple",
      code: 'export function parse(): ["ok", Payload] { return impl(); }',
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a union of tagged tuples",
      code: 'export function parse(): ["ok", Payload] | ["err", string] { return impl(); }',
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects readonly tuple boundaries",
      code: "export function parse(): readonly [Payload, Error | null] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects React-style hook tuples under the blanket boundary rule",
      code: "export function useToggle(): [boolean, (next: boolean) => void] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects accessor pairs",
      code: "export function createRef<T>(init: T): [T, (newValue: T) => void] { return impl(init); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects exported underscore-prefixed functions",
      code: "export function _decode(): [string, number] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // The canonical shape: distinct fields the caller must unpack by position.
    {
      code: "export function download(): [string, Headers, string | null] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a distinct-field tuple wrapped in Promise",
      code: "export async function fetchDoc(): Promise<[string, number]> { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a distinct-field tuple wrapped in PromiseLike",
      code: "export function fetchDoc(): PromiseLike<[string, number]> { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a distinct-field tuple wrapped in Awaited",
      code: "export function fetchDoc(): Awaited<[string, number]> { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an exported arrow function",
      code: "export const resolve = (): [User, boolean] => impl();",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Method on an exported class.
    {
      code: "export class Repo { find(): [Row, number] { return impl(); } }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Default export.
    {
      code: "export default function run(): [string, Error | null] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // --- Exported through a detached specifier, not the inline keyword. ---
    {
      code: "function split(s: string): [string, number] { return impl(s); }\nexport { split };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Renamed on the way out — the local binding is what the rule matches.
    {
      code: "function split(s: string): [string, number] { return impl(s); }\nexport { split as s };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // One specifier list can export several bindings.
    {
      code: "function split(s: string): [string, number] { return impl(s); }\nconst other = 1;\nexport { other, split };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Arrow function assigned to a const, exported later.
    {
      code: "const resolve = (): [User, boolean] => impl();\nexport { resolve };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Only the exported declarator of a multi-declarator statement is public.
    {
      code: "const resolve = (): [User, boolean] => impl(), local = (): [User, boolean] => impl();\nexport { resolve };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // A method of a class exported later — the class name carries the export.
    {
      code: "class Repo { find(): [Row, number] { return impl(); } }\nexport { Repo };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // `export default split` — the identifier form, not a declaration.
    {
      code: "function split(s: string): [string, number] { return impl(s); }\nexport default split;",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // TS `export =` assignment.
    {
      code: "function split(s: string): [string, number] { return impl(s); }\nexport = split;",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },

    {
      name: "rejects a literal tag outside the first tuple slot",
      code: 'export function parse(): [Payload, "ok"] { return impl(); }',
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "does not mistake an ordinary use-prefixed name for a React hook",
      code: "export function userTuple(): [User, boolean] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a three-slot tuple even when one slot is a callback",
      code: "export function open(u: string): [Socket, () => void, number] { return impl(u); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a two-slot tuple when neither slot is callable",
      code: "export function compilePath(p: string): [RegExp, CompiledPathParam[]] { return impl(p); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
  ],
});
