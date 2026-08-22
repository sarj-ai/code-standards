import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_POSITIONAL_TUPLE_RETURN_DOCUMENTATION } from "../../src/rules/no-positional-tuple-return.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

RULE_TESTER.run("no-positional-tuple-return", rule, {
  valid: [
    { name: "accepts the documented named object", code: NO_POSITIONAL_TUPLE_RETURN_DOCUMENTATION.examples[0].files[0].source },
    {
      name: "does not collide a nested interface name with an exported top-level interface",
      code: "export interface Loader {} namespace Internal { interface Loader { load(): [string, number]; } }",
    },
    // --- The named form, which is the whole point. ---
    {
      code: "export function download(): { body: string; contentType: string | null } { return impl(); }",
    },
    {
      name: "ignores generated declaration files when the rule is used standalone",
      filename: "/repo/src/__generated__/api.ts",
      code: "export function pair(): [string, number] { return impl(); }",
    },
    // --- Single-element tuple and array types are not positional records. ---
    { code: "export function one(): [string] { return impl(); }" },
    { code: "export function many(): Array<[string, number]> { return impl(); }" },
    // --- No return annotation to judge. ---
    { code: "export function inferred() { return ['a', 1]; }" },
    { name: "allows an anonymous inline const-tuple callback", code: "items.map(() => ['a', 1] as const);" },
    {
      name: "allows an opaque TanStack Query key factory",
      code: "export const userKeys = { all: ['users'] as const, detail: (id: string) => [...userKeys.all, id] as const } as const;",
    },
    { name: "explicit non-tuple contract wins over const implementation", code: "function pair(): unknown { return ['a', 1] as const; }" },
  ],
  invalid: [
    { name: "reports the documented tuple return", code: NO_POSITIONAL_TUPLE_RETURN_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noPositionalTupleReturn" }] },
    {
      name: "rejects a private method",
      code: "export class Loader { private load(): [string, number] { return impl(); } public run(): void {} }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a non-exported function",
      code: "function split(): [string, number] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an inferred const tuple from a named function",
      code: "function split() { return ['a', 1] as const; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "does not exempt an arbitrary Keys-suffixed object without an all-key anchor",
      code: "const resultKeys = { pair: () => ['a', 1] as const } as const;",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an inferred tuple assertion from a named arrow",
      code: "const split = () => ['a', 1] as [string, number];",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an inferred tuple satisfies expression",
      code: "function split() { return ['a', 1] satisfies [string, number]; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "reports one inferred tuple boundary even with multiple tuple returns",
      code: "function split(value: boolean) { if (value) return ['a', 1] as const; return ['b', 2] as const; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a nested named inferred const tuple",
      code: "function outer() { function split() { return ['a', 1] as const; } return split; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a nested declaration",
      code: "export function outer(): void { function local(): [string, number] { return impl(); } local(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a nested named arrow",
      code: "function outer(): void { const local = (): [string, number] => impl(); local(); } export { outer };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a named tuple callback inside class heritage setup",
      code: "export class Rollup extends factory({ make() { const pair = (): [string, number] => impl(); return pair; } }) {}",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an anonymous default function",
      code: "export default function (): [string, number] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an anonymous default arrow",
      code: "export default ((): [string, number] => impl());",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a public method on an exported class expression",
      code: "export const Loader = class { load(): [string, number] { return impl(); } };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a method on an exported object",
      code: "export const loader = { load(): [string, number] { return impl(); } };",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a public arrow property on an exported class",
      code: "export class Loader { load = (): [string, number] => impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "unwraps satisfies around an exported arrow function",
      code: "export const load = (((): [string, number] => impl()) satisfies Loader);",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "resolves a local tuple alias used by an exported function",
      code: "type Pair = [string, number]; export function pair(): Pair { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "reports each public use of a shared tuple alias at its own boundary",
      code: `
        type Pair = [string, number];
        export function first(): Pair { return impl(); }
        export function second(): Pair { return impl(); }
      `,
      errors: [
        { messageId: "noPositionalTupleReturn", line: 3 },
        { messageId: "noPositionalTupleReturn", line: 4 },
      ],
    },
    {
      name: "rejects a tuple return on an exported interface method",
      code: "export interface Loader { load(): [string, number]; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a string-literal interface method returning a tuple",
      code: 'export interface Loader { "load pair"(): [string, number]; }',
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an exported function-type alias returning a tuple",
      code: "export type Loader = () => [string, number];",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a callable alias chain returning a tuple",
      code: "type Pair = [string, number]; type Fn = () => Pair; export type Public = Fn;",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects callable members of an exported type literal",
      code: "export type API = { pair(): [string, number]; other: () => [string, number] };",
      errors: [
        { messageId: "noPositionalTupleReturn" },
        { messageId: "noPositionalTupleReturn" },
      ],
    },
    {
      name: "rejects a declaration-only callable class property",
      code: "export class API { pair: () => [string, number]; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a tuple contract inherited by an exported interface",
      code: "interface Base { pair(): [string, number]; } export interface API extends Base {}",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an exported declare function returning a tuple",
      code: "export declare function pair(): [string, number];",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an exported interface callable property returning a tuple",
      code: "export interface Loader { load: () => [string, number]; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects a string-literal callable property returning a tuple",
      code: 'export interface Loader { "load pair": () => [string, number]; }',
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    {
      name: "rejects an exported abstract method returning a tuple",
      code: "export abstract class Loader { abstract load(): [string, number]; }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
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
    // Every named declarator is checked, regardless of export status.
    {
      code: "const resolve = (): [User, boolean] => impl(), local = (): [User, boolean] => impl();\nexport { resolve };",
      errors: [
        { messageId: "noPositionalTupleReturn", data: { name: "resolve", count: "2" } },
        { messageId: "noPositionalTupleReturn", data: { name: "local", count: "2" } },
      ],
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
