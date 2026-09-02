import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION,
} from "../../src/rules/prefer-module-level-refined-schema.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});
const ZOD_IMPORT = `import { z } from "zod";`;
const ERROR = { messageId: "hoistRefinedSchema" as const };

RULE_TESTER.run("prefer-module-level-refined-schema", rule, {
  valid: [
    {
      name: "public no-match example",
      filename:
        PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION.examples[0].focusPath,
      code: PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION.examples[0]
        .files[0].source,
    },
    `${ZOD_IMPORT} const BatchSizeSchema = z.number().int().min(1).max(1000); export function parse(v: unknown) { return BatchSizeSchema.parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown, maximum: number) { return z.number().int().min(1).max(maximum).parse(v); }`,
    `${ZOD_IMPORT} export function parse<T>() { return z.custom<T>(); }`,
    `${ZOD_IMPORT} export function parse() { const value = "a"; return z.literal(value); }`,
    `${ZOD_IMPORT} let maximum = 10; export function configure(value: number) { maximum = value; } export function parse(v: unknown) { return z.number().max(maximum).parse(v); }`,
    `${ZOD_IMPORT} import { allowedNow } from "./policy.js"; export function parse(v: unknown) { return z.enum(allowedNow()).parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown) { return z.object({ value: z.string() }).parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown) { return z.enum(["a", "b"]).parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown) { return z.lazy(() => z.string()).parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown) { return z.unknown().parse(v); }`,
    `${ZOD_IMPORT} export function parse(v: unknown) { return z.any().parse(v); }`,
    {
      name: "ignores a schema that reads this",
      code: `${ZOD_IMPORT} export class Parser { enabled = true; parse(v: unknown) { return z.string().refine(() => this.enabled).parse(v); } }`,
    },
    {
      name: "ignores a schema that reads arguments",
      code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.string().refine(() => arguments.length > 0).parse(v); }`,
    },
    {
      name: "ignores a schema that reads super",
      code: `${ZOD_IMPORT} class Base { protected static enabled = true; } export class Parser extends Base { static parse(v: unknown) { return z.string().refine(() => super.enabled).parse(v); } }`,
    },
    {
      name: "ignores a shadowed Zod import",
      code: `${ZOD_IMPORT} export function parse(z: Builder) { return z.string(); }`,
    },
    {
      name: "ignores test-local schemas",
      filename: "src/options.test.ts",
      code: `${ZOD_IMPORT} function parse(v: unknown) { return z.string().parse(v); }`,
    },
    {
      name: "ignores benchmark-local schemas",
      filename: "/repo/benchmarks/options.ts",
      code: `${ZOD_IMPORT} function parse(v: unknown) { return z.string().parse(v); }`,
    },
    {
      name: "ignores generated schemas",
      filename: "src/options.ts",
      code: `// @generated\n${ZOD_IMPORT} function parse(v: unknown) { return z.string().parse(v); }`,
    },
    {
      name: "ignores another package named z",
      code: `import { z } from "zero-lib"; function parse() { return z.string(); }`,
    },
  ],
  invalid: [
    {
      name: "public match example",
      filename:
        PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION.examples[1].focusPath,
      code: PREFER_MODULE_LEVEL_REFINED_SCHEMA_DOCUMENTATION.examples[1]
        .files[0].source,
      errors: [ERROR],
    },
    {
      name: "reports the motivating closed string schema",
      code: `${ZOD_IMPORT} export function parse(key: unknown) { const KeySchema = z.string().trim().min(1).max(128); return KeySchema.parse(key); }`,
      errors: [ERROR],
      output: null,
    },
    {
      name: "reports a bare scalar schema",
      code: `${ZOD_IMPORT} export function schema() { return z.string(); }`,
      errors: [ERROR],
    },
    {
      name: "reports an inline one-off parse schema",
      code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.string().parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports a closed module-constant refinement",
      code: `${ZOD_IMPORT} const MAX = 1000; export function parse(v: unknown) { return z.number().int().min(1).max(MAX).parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports an array schema without reporting its item schema",
      code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.array(z.string()).parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports a wrapper factory without reporting its inner schema",
      code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.optional(z.string()).parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports a namespaced coerce schema",
      code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.coerce.date().parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports a namespaced ISO schema",
      code: `${ZOD_IMPORT} export function parse(v: unknown) { return z.iso.datetime().parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports aliased Zod imports",
      code: `import { z as schema } from "zod/v4"; export function parse(v: unknown) { return schema.boolean().parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "reports namespace Zod imports",
      code: `import * as schema from "zod"; export function parse(v: unknown) { return schema.literal(true).parse(v); }`,
      errors: [ERROR],
    },
    {
      name: "uses the outermost function as the hoist boundary",
      code: `${ZOD_IMPORT} export function outer() { return () => z.string(); }`,
      errors: [ERROR],
    },
  ],
});
