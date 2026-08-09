import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { preferZodInferDocumentation } from "../../src/rules/prefer-zod-infer.js";

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
    { name: "accepts the documented inferred type", code: preferZodInferDocumentation.examples[0].files[0].source },
    // The supported shape: the type is derived, so it cannot drift.
    `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
     type User = z.infer<typeof UserSchema>;`,
    `${IMPORT}const UserSchema = z.object({ id: z.string() });
     type UserInput = z.input<typeof UserSchema>;
     type UserOutput = z.output<typeof UserSchema>;`,

    // An identical key set without name correlation is insufficient.
    `${IMPORT}const userSchema = z.object({ id: z.string(), name: z.string() });
     interface DatabaseRow { id: string; name: string }`,

    // A `z.ZodType<T>` annotation intentionally constrains a schema.
    `${IMPORT}type ApiKeyInput = { id: string; label?: string };
     const ApiKeyInputSchema: z.ZodType<ApiKeyInput> = z.object({ id: z.string(), label: z.string().optional() });`,
    // Every argument in the three-parameter form is protected.
    `${IMPORT}type QueryRaw = { limit: string };
     type Query = { limit: string };
     const QuerySchema: z.ZodType<Query, z.ZodTypeDef, QueryRaw> = z.object({ limit: z.string() });`,

    // `z.infer` cannot reproduce a caller-supplied generic parameter.
    `${IMPORT}const PageSchema = z.object({ items: z.unknown(), total: z.number() });
     type Page<T> = { items: T[]; total: number };`,
    {
      name: "does not report a generic interface that inference cannot express",
      code: `${IMPORT}const PageSchema = z.object({ items: z.unknown(), total: z.number() });
             interface Page<T> { items: T[]; total: number }`,
    },

    // A lenient wire schema and strict domain type are not twins.
    `${IMPORT}const ZReadingSchema = z.looseObject({ celsius: z.number().nullish(), taken: z.string().nullish() });
     interface Reading { celsius: number; taken: string }`,
    `${IMPORT}const SettingsSchema = z.object({ theme: z.string() }).partial();
     interface Settings { theme: string }`,
    `${IMPORT}const BaseSchema = z.object({ id: z.string() });
     const UserSchema = BaseSchema.extend({ name: z.string() });
     interface User { id: string; name: string }`,
    {
      name: "does not report schemas whose shape is changed by object modifiers",
      code: `${IMPORT}
             const OmittedSchema = z.object({ id: z.string(), secret: z.string() }).omit({ secret: true });
             interface Omitted { id: string }
             const PassthroughSchema = z.object({ id: z.string() }).passthrough();
             interface Passthrough { id: string }
             const CatchallSchema = z.object({ id: z.string() }).catchall(z.string());
             interface Catchall { id: string }
             const MergedSchema = z.object({ id: z.string() }).merge(z.object({ name: z.string() }));
             interface Merged { id: string; name: string }`,
    },

    // Guard (e): the shapes disagree, so the type is deliberately different.
    `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
     interface User { id: string; name: string; displayName: string }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string(), nickname: z.string().optional() });
     interface User { id: string; nickname: string }`,
    {
      name: "does not treat output defaults as optional properties",
      code: `${IMPORT}const UserSchema = z.object({ name: z.string().default("anonymous") });
             interface User { name?: string }`,
    },
    `${IMPORT}const UserSchema = z.object({ id: z.string(), age: z.number() });
     interface User { id: string; age: string }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string() });
     interface User { readonly id: string }`,
    `${IMPORT}const EventSchema = z.object({ createdAt: z.date() });
     interface Event { createdAt: CustomDate }`,
    `${IMPORT}const UserSchema = z.object({ tags: z.array(z.string()).readonly() });
     interface User { tags: readonly string[] }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string(), deletedAt: z.string().nullable() });
     interface User { id: string; deletedAt: string }`,

    // A transformed schema may have a separate post-transform type.
    `${IMPORT}const UserSchema = z.object({ user_id: z.string(), name: z.string() });
     const UserCamel = UserSchema.transform((row) => ({ userId: row.user_id, name: row.name }));
     interface User { user_id: string; name: string }`,
    // Same for a field-level transform.
    `${IMPORT}const UserSchema = z.object({ id: z.string(), tags: z.string().transform((value) => value.split(",")) });
     interface User { id: string; tags: string }`,
    {
      name: "does not report schemas piped or preprocessed elsewhere in the module",
      code: `${IMPORT}
             const PipedSchema = z.object({ id: z.string() });
             const PipedOutput = PipedSchema.pipe(z.object({ id: z.string() }));
             interface Piped { id: string }
             const PreprocessedSchema = z.object({ id: z.string() });
             const PreprocessedOutput = PreprocessedSchema.preprocess((value) => value);
             interface Preprocessed { id: string }`,
    },

    // An extended interface is not a direct restatement.
    `${IMPORT}interface Base { createdAt: string }
     const UserSchema = z.object({ id: z.string() });
     interface User extends Base { id: string }`,
    {
      name: "does not report aliases that are not bare object literals",
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             type User = BaseUser & { id: string };`,
    },

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
    {
      name: "does not report twins in story files",
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      filename: "src/User.stories.tsx",
    },

    // Escape hatch.
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      options: [{ ignoreTypeNames: ["^User$"] }],
    },
  ],

  invalid: [
    { name: "reports the documented hand-written twin", code: preferZodInferDocumentation.examples[1].files[0].source, errors: [{ messageId: "handWrittenTwin", data: { typeName: "User", schemaName: "UserSchema" } }] },
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
             interface User { id: string; name: string }`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "User", schemaName: "UserSchema" } }],
    },
    // Declaration order does not affect pairing.
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
    {
      name: "reports twins behind shape-preserving schema chains",
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() }).refine((user) => user.id.length > 0).meta({ title: "User" });
             interface User { id: string }`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "reports a strictObject twin",
      code: `${IMPORT}const UserSchema = z.strictObject({ id: z.string(), active: z.boolean() });
             type User = { id: string; active: boolean };`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "reports a required output property supplied by a schema default",
      code: `${IMPORT}const UserSchema = z.object({ name: z.string().default("anonymous") });
             interface User { name: string }`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "recognizes the exact Date type inferred by z.date",
      code: `${IMPORT}const EventSchema = z.object({ createdAt: z.date() });
             interface Event { createdAt: Date }`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    // The loose tier reports on name correlation without requiring equal shapes.
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string; nickname: string }`,
      options: [{ requireIdenticalShape: false }],
      errors: [{ messageId: "handWrittenTwin" }],
    },
  ],
});
