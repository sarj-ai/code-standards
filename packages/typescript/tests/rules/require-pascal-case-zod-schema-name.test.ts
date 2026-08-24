import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  REQUIRE_PASCAL_CASE_ZOD_SCHEMA_NAME_DOCUMENTATION,
} from "../../src/rules/require-pascal-case-zod-schema-name.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();
const zod = (code: string): string => `import { z } from "zod"; ${code}`;
const ERROR = { messageId: "requirePascalSchema" as const };

RULE_TESTER.run("require-pascal-case-zod-schema-name", rule, {
  valid: [
    {
      name: "accepts the documented PascalCase schema contract",
      code: REQUIRE_PASCAL_CASE_ZOD_SCHEMA_NAME_DOCUMENTATION.examples[0].files[0].source,
    },
    { code: zod("const UserSchema = z.object({ name: z.string() });") },
    { code: zod("const URLSchema = z.url();") },
    { code: zod("const RoleSchema = z.enum(['admin', 'user']);") },
    { code: zod("const UserSchema = z.strictObject({ id: z.uuid() }).readonly();") },
    { code: zod("const DateSchema = z.coerce.date();") },
    { code: zod("const DateTimeSchema = z.iso.datetime();") },
    {
      name: "accepts a same-file derived schema contract",
      code: zod("const UserSchema = z.object({ id: z.string() }); const AdminSchema = UserSchema.extend({ admin: z.literal(true) });"),
    },
    {
      name: "accepts a same-file schema alias",
      code: zod("const UserSchema = z.object({ id: z.string() }); const PublicUserSchema = UserSchema;"),
    },
    {
      name: "ignores function-local schema helpers",
      code: zod("function parse() { const itemSchema = z.object({ id: z.string() }); return itemSchema.parse(input); }"),
    },
    {
      name: "ignores test-local schemas",
      code: 'import { z } from "zod"; const itemSchema = z.object({ id: z.string() });',
      filename: "/repo/src/item.test.ts",
    },
    {
      name: "ignores benchmark schemas",
      code: 'import { z } from "zod"; const itemSchema = z.object({ id: z.string() });',
      filename: "/repo/benchmarks/item.ts",
    },
    {
      name: "ignores generated schemas",
      code: '// @generated\nimport { z } from "zod"; export const itemSchema = z.object({ id: z.string() });',
      filename: "/repo/src/item.ts",
    },
    {
      name: "ignores Zod calls returning values and result envelopes",
      code: zod(`const parsed = z.string().parse(value);
        const result = z.string().safeParse(value);
        const encoded = z.codec(z.string(), z.string(), handlers).encode(value);
        const json = z.toJSONSchema(UserSchema);
        const registry = z.registry();
        const configured = z.config({});`),
    },
    {
      name: "ignores arbitrary wrapper factory results",
      code: "const userSchema = createSchema();",
    },
    {
      name: "ignores imported and re-exported external schema names",
      code: 'import { userSchema } from "./contracts.js"; export { userSchema };',
    },
    {
      name: "does not confuse another package namespace for Zod",
      code: 'import z from "zero-lib"; const USER_SCHEMA = z.object({ id: z.string() });',
    },
    {
      name: "does not confuse a shadowing local binding for Zod",
      code: 'import { z } from "zod"; function build(z: Builder) { const USER_SCHEMA = z.object({}); return USER_SCHEMA; }',
    },
    { code: "const USER_SCHEMA = Object.freeze({ id: 'string' });" },
  ],
  invalid: [
    {
      name: "reports the documented screaming-snake schema name",
      code: REQUIRE_PASCAL_CASE_ZOD_SCHEMA_NAME_DOCUMENTATION.examples[1].files[0].source,
      errors: [ERROR],
    },
    { code: zod("const userSchema = z.object({});"), errors: [ERROR] },
    { code: zod("const ZUser = z.object({});"), errors: [ERROR] },
    { code: zod("const User = z.object({});"), errors: [ERROR] },
    { code: zod("const schema = z.object({});"), errors: [ERROR] },
    { code: zod("const schema1 = z.string();"), errors: [ERROR] },
    { code: zod("const numberSchemaOptional = z.number().optional();"), errors: [ERROR] },
    { code: zod("const USER_SCHEMA = z.strictObject({});"), errors: [ERROR] },
    {
      name: "reports a derived schema with a noncanonical name",
      code: zod("const UserSchema = z.object({}); const adminSchema = UserSchema.extend({ admin: z.boolean() });"),
      errors: [ERROR],
    },
    {
      name: "reports a noncanonical same-file schema alias",
      code: zod("const UserSchema = z.object({}); const USER_ALIAS = UserSchema;"),
      errors: [ERROR],
    },
    {
      name: "supports aliased Zod imports",
      code: 'import { z as schema } from "zod/v4"; export const MUTATION_ROUTE_BASE_SCHEMA = schema.strictObject({ lifecycle: schema.enum(["active", "deprecated"]) });',
      errors: [ERROR],
    },
    {
      name: "supports namespace Zod imports",
      code: 'import * as zod from "zod"; const itemSchema = zod.object({ id: zod.string() });',
      errors: [ERROR],
    },
    {
      name: "supports default Zod imports",
      code: 'import zod from "zod/mini"; const itemSchema = zod.object({ id: zod.string() });',
      errors: [ERROR],
    },
    {
      name: "does not treat a benchmarking filename as a benchmark directory",
      code: zod("const itemSchema = z.object({});"),
      filename: "/repo/src/benchmarking-report.ts",
      errors: [ERROR],
    },
  ],
});
