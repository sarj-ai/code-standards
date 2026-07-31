import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-zod-infer.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});

const IMPORT = 'import { z } from "zod";\n';

ruleTester.run("prefer-zod-infer", rule, {
  valid: [
    // The supported shape: the type is derived, so it cannot drift.
    `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
     type User = z.infer<typeof UserSchema>;`,
    `${IMPORT}const UserSchema = z.object({ id: z.string() });
     type UserInput = z.input<typeof UserSchema>;
     type UserOutput = z.output<typeof UserSchema>;`,

    // No name correlation. Measured: key-set coincidence alone was 4/13
    // precision on the corpus, so an unrelated name is never enough.
    `${IMPORT}const userSchema = z.object({ id: z.string(), name: z.string() });
     interface DatabaseRow { id: string; name: string }`,

    // Guard (c): `z.ZodType<T>` is the supported way to constrain a schema to an
    // existing type — inference in the other direction, on purpose.
    `${IMPORT}type ApiKeyInput = { id: string; label?: string };
     const ApiKeyInputSchema: z.ZodType<ApiKeyInput> = z.object({ id: z.string(), label: z.string().optional() });`,
    // ...including the three-parameter `ZodType<Output, Def, Input>` form, where
    // the hand-written type is the THIRD argument.
    `${IMPORT}type QueryRaw = { limit: string };
     type Query = { limit: string };
     const QuerySchema: z.ZodType<Query, z.ZodTypeDef, QueryRaw> = z.object({ limit: z.string() });`,

    // Guard (b): `z.infer` cannot produce a generic, so a generic twin is not one.
    `${IMPORT}const PageSchema = z.object({ items: z.unknown(), total: z.number() });
     type Page<T> = { items: T[]; total: number };`,

    // Guard (d): a lenient wire schema paired with the strict domain type a
    // parse function returns is parse-don't-validate, not duplication.
    `${IMPORT}const ZReadingSchema = z.looseObject({ celsius: z.number().nullish(), taken: z.string().nullish() });
     interface Reading { celsius: number; taken: string }`,
    `${IMPORT}const SettingsSchema = z.object({ theme: z.string() }).partial();
     interface Settings { theme: string }`,
    `${IMPORT}const BaseSchema = z.object({ id: z.string() });
     const UserSchema = BaseSchema.extend({ name: z.string() });
     interface User { id: string; name: string }`,

    // Guard (e): the shapes disagree, so the type is deliberately different.
    `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
     interface User { id: string; name: string; displayName: string }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string(), nickname: z.string().optional() });
     interface User { id: string; nickname: string }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string(), age: z.number() });
     interface User { id: string; age: string }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string(), deletedAt: z.string().nullable() });
     interface User { id: string; deletedAt: string }`,

    // Guard (f): the module transforms the schema, so the hand-written type
    // plausibly describes the POST-transform value and `z.infer<typeof
    // UserSchema>` would be the wrong advice.
    `${IMPORT}const UserSchema = z.object({ user_id: z.string(), name: z.string() });
     const UserCamel = UserSchema.transform((row) => ({ userId: row.user_id, name: row.name }));
     interface User { user_id: string; name: string }`,
    // Same for a field-level transform.
    `${IMPORT}const UserSchema = z.object({ id: z.string(), tags: z.string().transform((value) => value.split(",")) });
     interface User { id: string; tags: string }`,

    // Guard (g): a type that extends something adds to the schema's shape.
    `${IMPORT}interface Base { createdAt: string }
     const UserSchema = z.object({ id: z.string() });
     interface User extends Base { id: string }`,

    // Every member is a reference, so nothing positively agrees — a bare name
    // and key-set match is not enough to call it a restatement.
    `${IMPORT}const RoleSchema = z.object({ id: z.string() });
     const UserSchema = z.object({ role: RoleSchema, backupRole: RoleSchema });
     interface User { role: Role; backupRole: Role }`,

    // Not Zod at all.
    `const z = builder; const UserSchema = z.object({ id: z.string() });
     interface User { id: string }`,

    // Guard (a): fixtures declare the two halves of an assertion side by side.
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      filename: "src/parse.test.ts",
    },
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      filename: "src/generated/api.ts",
    },

    // Escape hatch.
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      options: [{ ignoreTypeNames: ["^User$"] }],
    },
  ],

  invalid: [
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
             interface User { id: string; name: string }`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "User", schemaName: "UserSchema" } }],
    },
    // The type may be declared BEFORE the schema — the pairing runs at
    // Program:exit, which is how the two public `types.ts` hits look.
    {
      code: `${IMPORT}export interface ApiConfig { type: string; endpoint?: string }
             export const apiConfigSchema = z.object({ type: z.string(), endpoint: z.string().optional() });`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "ApiConfig", schemaName: "apiConfigSchema" } }],
    },
    // The `Z`-prefix convention and a type alias rather than an interface.
    {
      code: `${IMPORT}const ZJobOptionsSchema = z.object({ id: z.string().optional(), name: z.string(), attempts: z.number() });
             type JobOptions = { id?: string; name: string; attempts: number };`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "JobOptions", schemaName: "ZJobOptionsSchema" } }],
    },
    // `XType` is the same claim as `X`.
    {
      code: `${IMPORT}const settingsSchema = z.object({ theme: z.string(), compact: z.boolean() });
             interface SettingsType { theme: string; compact: boolean }`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    // Nullable and optional agree member for member.
    {
      code: `${IMPORT}const RowSchema = z.object({ id: z.string(), label: z.string().nullable(), note: z.string().optional() });
             interface Row { id: string; label: string | null; note?: string }`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    // A namespace import, and `.describe()` does not change the inferred type.
    {
      code: `import * as zod from "zod";
             const eventSchema = zod.object({ kind: zod.literal("click"), at: zod.number() }).describe("an event");
             interface Event { kind: "click"; at: number }`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    // `requireIdenticalShape: false` is the looser tier measured at 8 reports
    // (1 of them noise): the name correlation alone is the finding.
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string; nickname: string }`,
      options: [{ requireIdenticalShape: false }],
      errors: [{ messageId: "handWrittenTwin" }],
    },
  ],
});
