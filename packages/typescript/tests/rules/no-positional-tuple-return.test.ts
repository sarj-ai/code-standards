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
    // --- Homogeneous pairs are a range/coordinate, not distinct fields. ---
    { code: "export function bounds(): [number, number] { return impl(); }" },
    { code: "export function window(): [Date, Date] { return impl(); }" },
    // --- Variadic tuples are sequences, not records. ---
    { code: "export function args(): [string, ...number[]] { return impl(); }" },
    // --- Labeled members already carry the names to the call site. ---
    {
      code: "export function respond(): [status: number, body: string] { return impl(); }",
    },
    // --- A literal first element makes the tuple the discriminated union. ---
    {
      code: 'export function parse(): ["ok", Payload] | ["err", string] { return impl(); }',
    },
    // --- React hooks: `[value, setValue]` is the ecosystem contract. ---
    {
      code: "export function useToggle(): [boolean, (next: boolean) => void] { return impl(); }",
    },
    {
      code: "export const useCounter = (): [number, () => void] => impl();",
    },
    // --- Not exported: the call sites live in this file. ---
    {
      code: "function split(): [string, number] { return impl(); }",
    },
    // --- Single-element tuple and array types are not positional records. ---
    { code: "export function one(): [string] { return impl(); }" },
    { code: "export function many(): Array<[string, number]> { return impl(); }" },
    // --- No return annotation to judge. ---
    { code: "export function inferred() { return ['a', 1]; }" },
  ],
  invalid: [
    // The canonical shape: distinct fields the caller must unpack by position.
    {
      code: "export function download(): [string, Headers, string | null] { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Wrapped in a Promise, which is where async boundaries put it.
    {
      code: "export async function fetchDoc(): Promise<[string, number]> { return impl(); }",
      errors: [{ messageId: "noPositionalTupleReturn" }],
    },
    // Exported arrow function.
    {
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
  ],
});
