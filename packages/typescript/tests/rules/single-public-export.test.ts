import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/single-public-export.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("single-public-export", rule, {
  valid: [
    // FP guard, corpus: react-router/packages/react-router/__tests__/server-runtime/utils.ts:20
    // — a suite's shared helper module is `utils.ts` by convention.
    {
      code: "export function mockServerBuild(routes) { return routes; }",
      filename: "/repo/packages/x/__tests__/server-runtime/utils.ts",
    },
    // Non-junk-drawer stem: informative name is never flagged even with one export.
    {
      filename: "src/user-service.ts",
      code: `export function createUser() {}`,
    },
    // Junk stem but ≥2 exports — ambiguous rename target, do not fire.
    {
      filename: "src/utils.ts",
      code: `
        export function formatDate() {}
        export function parseDate() {}
      `,
    },
    // Junk stem, one function AND a type export — the type is another export.
    {
      filename: "src/utils.ts",
      code: `
        export type Options = { verbose: boolean };
        export function run(o: Options) { return o; }
      `,
    },
    // index barrel — excluded from the junk set entirely.
    {
      filename: "src/index.ts",
      code: `export { createUser } from "./user-service.js";`,
    },
    // Pure re-export file with a junk stem — a barrel, not an owner. Skip.
    {
      filename: "src/types.ts",
      code: `export { UserId } from "./user-id.js";`,
    },
    // export * re-export barrel.
    {
      filename: "src/models.ts",
      code: `export * from "./user.js";`,
    },
    // Type-only module — a lone `export type` is not a fn/class/const, so 0
    // qualifying candidates: `types.ts` is idiomatic for these, do not fire.
    {
      filename: "src/types.ts",
      code: `export type UserId = string & { readonly brand: unique symbol };`,
    },
    // Single interface export — same reasoning as type-only.
    {
      filename: "src/models.ts",
      code: `export interface User { name: string }`,
    },
    // Value-constant export (not a function const) — renaming after a bare
    // constant loses more than it gains.
    {
      filename: "src/constants.ts",
      code: `export const MAX_RETRIES = 5;`,
    },
    // `.d.ts` declaration files are skipped.
    {
      filename: "src/types.d.ts",
      code: `export function foo(): void;`,
    },
    // Test files are skipped.
    {
      filename: "src/utils.test.ts",
      code: `export function makeFixture() {}`,
    },
    // Spec files are skipped.
    {
      filename: "src/helpers.spec.ts",
      code: `export function makeFixture() {}`,
    },
    // Stem already equals the kebab-cased export name — nothing to improve.
    {
      filename: "src/utils.ts",
      code: `export function utils() {}`,
    },
    // No exports at all.
    {
      filename: "src/helpers.ts",
      code: `function internal() {}`,
    },
    // shadcn `cn` className helper — conventional bucket export, exempt.
    {
      filename: "src/lib/utils.ts",
      code: `export function cn(...inputs: unknown[]) { return inputs.join(" "); }`,
    },
    // Value export co-located with its own companion type alias — two exports,
    // the type is a second export so the rename target is ambiguous.
    {
      filename: "src/utils.ts",
      code: `
        export type ClientConfig = { retries: number };
        export function makeClient(c: ClientConfig) { return c; }
      `,
    },
    // Function-const co-located with a companion interface.
    {
      filename: "src/common.ts",
      code: `
        export interface ParseResult { ok: boolean }
        export const parse = (s: string): ParseResult => ({ ok: s.length > 0 });
      `,
    },
    // Config const paired with the type that describes it.
    {
      filename: "src/constants.ts",
      code: `
        export type Config = { verbose: boolean };
        export const config: Config = { verbose: false };
      `,
    },
    // Component paired with its Props interface — two exports, not flagged.
    {
      filename: "src/common.tsx",
      code: `
        export interface Props { title: string }
        export default function Widget(props: Props) { return props.title; }
      `,
    },
    // Pure type-only module exporting several type aliases.
    {
      filename: "src/types.ts",
      code: `
        export type UserId = string;
        export type OrgId = string;
        export type Pair = [UserId, OrgId];
      `,
    },
    // Function export alongside a local type-only re-specifier export.
    {
      filename: "src/helpers.ts",
      code: `
        type Opts = { loud: boolean };
        export function run(o: Opts) { return o; }
        export type { Opts };
      `,
    },
    // Type-only re-export barrel with a junk stem — a re-export, skip.
    {
      filename: "src/types.ts",
      code: `export type { UserId } from "./user-id.js";`,
    },
    // Lone enum in a junk stem — not a fn/class/const candidate, do not fire.
    {
      filename: "src/constants.ts",
      code: `export enum Direction { Up, Down }`,
    },
    // Lone value-object const (not a function) — no rename candidate.
    {
      filename: "src/constants.ts",
      code: `export const DEFAULTS = { retries: 3, timeout: 1000 } as const;`,
    },
    // Mixed re-export barrel: a local decl plus a wildcard re-export — the
    // re-export marks this as an aggregator, not a single-responsibility owner.
    {
      filename: "src/shared.ts",
      code: `
        export * from "./primitives.js";
        export function helper() {}
      `,
    },
  ],
  invalid: [
    // Junk stem `utils` with a single exported function.
    {
      filename: "src/utils.ts",
      code: `export function snakeCaseText(s: string) { return s; }`,
      errors: [
        {
          messageId: "renameJunkDrawer",
          data: { stem: "utils", name: "snakeCaseText", expected: "snake-case-text" },
        },
      ],
    },
    // Junk stem `helpers` with a single exported class.
    {
      filename: "src/helpers.ts",
      code: `export class RetryPolicy {}`,
      errors: [
        {
          messageId: "renameJunkDrawer",
          data: { stem: "helpers", name: "RetryPolicy", expected: "retry-policy" },
        },
      ],
    },
    // Junk stem `common` with a single exported arrow-function const.
    {
      filename: "src/common.ts",
      code: `export const parseHttpDate = (s: string) => new Date(s);`,
      errors: [
        {
          messageId: "renameJunkDrawer",
          data: { stem: "common", name: "parseHttpDate", expected: "parse-http-date" },
        },
      ],
    },
    // Acronym run handling: `HTTPServer` -> `http-server`.
    {
      filename: "src/models.ts",
      code: `export class HTTPServer {}`,
      errors: [
        {
          messageId: "renameJunkDrawer",
          data: { stem: "models", name: "HTTPServer", expected: "http-server" },
        },
      ],
    },
    // default-exported named function.
    {
      filename: "src/util.ts",
      code: `export default function computeChecksum() {}`,
      errors: [
        {
          messageId: "renameJunkDrawer",
          data: { stem: "util", name: "computeChecksum", expected: "compute-checksum" },
        },
      ],
    },
  ],
});
