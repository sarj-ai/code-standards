// vitest: shared-module-graph
import rule from "../../src/rules/prefer-zod-infer.js";
import { RuleTester } from "./_tester.js";

const RULE_TESTER = new RuleTester({
  eslintCompat: true,
  languageOptions: { parserOptions: { lang: "ts" } },
});

const INFERRED_TYPE_EXAMPLE = 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); type User = z.infer<typeof UserSchema>;';
const HANDWRITTEN_TWIN_EXAMPLE = 'import { z } from "zod"; const UserSchema = z.object({ id: z.string() }); interface User { id: string }';

const IMPORT = 'import { z } from "zod";\n';

RULE_TESTER.run("prefer-zod-infer", rule, {
  valid: [
{"name":"explicit-widening-generic","code":"import {z} from 'zod'; const StateSchema=z.enum<string[]>(['ran','failed']); type State='ran'|'failed';"},
{"name":"cast-factory-callee","code":"import {z} from 'zod'; const StateSchema=(z.enum as (values: string[])=>z.ZodType<string>)(['ran','failed']); type State='ran'|'failed';"},
{"name":"cast-namespace-receiver","code":"import {z} from 'zod'; const StateSchema=(z as {enum(values: string[]):z.ZodType<string>}).enum(['ran','failed']); type State='ran'|'failed';"},
{"name":"outer-schema-cast","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']) as z.ZodType<string>; type State='ran'|'failed';"},
{"name":"widened-array-cast","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed'] as string[]); type State='ran'|'failed';"},
{"name":"widened-element-cast","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran' as string,'failed']); type State='ran'|'failed';"},
{"name":"contextually-widened-array","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed'] satisfies string[]); type State='ran'|'failed';"},
{"name":"type-asserted-array","code":"import {z} from 'zod'; const StateSchema=z.enum(<string[]>['ran','failed']); type State='ran'|'failed';"},
{"name":"different-domain","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); type State='ran'|'skipped';"},
{"name":"different-owner","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); type Other='ran'|'failed';"},
{"name":"already-inferred","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); type State=z.infer<typeof StateSchema>;"},
{"name":"widened-schema","code":"import {z} from 'zod'; const StateSchema: z.ZodType<string>=z.enum(['ran','failed']); type State='ran'|'failed';"},
{"name":"constrained-enum","code":"import {z} from 'zod'; type State='ran'|'failed'; const StateSchema=z.enum(['ran','failed']) satisfies z.ZodType<State>;"},
{"name":"transformed-enum","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']).transform(x=>x.length); type State='ran'|'failed';"},
{"name":"dynamic-enum","code":"import {z} from 'zod'; const StateSchema=z.enum(values); type State='ran'|'failed';"},
{"name":"nested-type","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); function read(){type State='ran'|'failed';}"},
{"name":"nested-schema","code":"import {z} from 'zod'; function build(){const StateSchema=z.enum(['ran','failed']);} type State='ran'|'failed';"},
{"name":"unrelated-builder","code":"import {z} from 'zod'; const StateSchema=builder.enum(['ran','failed']); type State='ran'|'failed';"},
{"name":"generic-alias","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); type State<T>='ran'|'failed';"},
{"name":"nullable-enum","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']).nullable(); type State='ran'|'failed';"},
{"name":"ambiguous-schemas","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); const ZState=z.enum(['ran','failed']); type State='ran'|'failed';"},
    { name: "requires proof for every field rather than one matching primitive", code: `${IMPORT}const UserSchema = z.object({ id: z.string(), payload: SomeSchema }); interface User { id: string; payload: OtherType }` },
    { name: "leaves matching collection shapes for manual type-aware review", code: `${IMPORT}const UserSchema = z.object({ id: z.string(), tags: z.array(z.string()) }); interface User { id: string; tags: string[] }` },
    { name: "does not pair a local schema with a module type", code: `${IMPORT}function build() { const UserSchema = z.object({ id: z.string() }); return UserSchema; } interface User { id: string }` },
    { name: "does not pair a local type with a module schema", code: `${IMPORT}const UserSchema = z.object({ id: z.string() }); function run() { interface User { id: string } }` },
    { name: "does not equate different array element types", code: `${IMPORT}const UserSchema = z.object({ id: z.string(), tags: z.array(z.string()) }); interface User { id: string; tags: number[] }` },
    { name: "does not equate different nested object shapes", code: `${IMPORT}const UserSchema = z.object({ id: z.string(), child: z.object({ value: z.string() }) }); interface User { id: string; child: { value: number } }` },
    { name: "accepts the documented inferred type", code: INFERRED_TYPE_EXAMPLE },

    `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
     type User = z.infer<typeof UserSchema>;`,
    `${IMPORT}const UserSchema = z.object({ id: z.string() });
     type UserInput = z.input<typeof UserSchema>;
     type UserOutput = z.output<typeof UserSchema>;`,

    `${IMPORT}const userSchema = z.object({ id: z.string(), name: z.string() });
     interface DatabaseRow { id: string; name: string }`,

    `${IMPORT}type ApiKeyInput = { id: string; label?: string };
     const ApiKeyInputSchema: z.ZodType<ApiKeyInput> = z.object({ id: z.string(), label: z.string().optional() });`,

    `${IMPORT}type QueryRaw = { limit: string };
     type Query = { limit: string };
     const QuerySchema: z.ZodType<Query, z.ZodTypeDef, QueryRaw> = z.object({ limit: z.string() });`,

    `${IMPORT}const PageSchema = z.object({ items: z.unknown(), total: z.number() });
     type Page<T> = { items: T[]; total: number };`,
    {
      name: "does not report a generic interface that inference cannot express",
      code: `${IMPORT}const PageSchema = z.object({ items: z.unknown(), total: z.number() });
             interface Page<T> { items: T[]; total: number }`,
    },

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
    {
      name: "does not equate different literal values",
      code: `${IMPORT}const EventSchema = z.object({ kind: z.literal("click"), at: z.number() });
             interface Event { kind: "hover"; at: number }`,
    },
    {
      name: "does not equate different enum domains",
      code: `${IMPORT}const JobSchema = z.object({ state: z.enum(["queued", "running"]), id: z.string() });
             interface Job { state: "queued" | "failed"; id: string }`,
    },
    {
      name: "does not trust dynamic enum domains",
      code: `${IMPORT}const states = ["queued", "running"] as const;
             const JobSchema = z.object({ state: z.enum(states), id: z.string() });
             interface Job { state: "queued" | "running"; id: string }`,
    },
    {
      name: "does not trust domains changed by outer Zod methods",
      code: `${IMPORT}
             const ArraySchema = z.object({ state: z.enum(["a", "b"]).array(), id: z.string() });
             interface Array { state: "a" | "b"; id: string }
             const UnionSchema = z.object({ state: z.enum(["a", "b"]).or(z.literal("c")), id: z.string() });
             interface Union { state: "a" | "b"; id: string }
             const PromiseSchema = z.object({ state: z.enum(["a", "b"]).promise(), id: z.string() });
             interface Promise { state: "a" | "b"; id: string }
             const ExcludedSchema = z.object({ state: z.enum(["a", "b"]).exclude(["b"]), id: z.string() });
             interface Excluded { state: "a" | "b"; id: string }`,
    },
    {
      name: "does not report repeated unions without an existing inferred alias",
      code: `${IMPORT}const ZOpenAIServiceTier = z.enum(["default", "fast"]);
             interface GlobalConfig { service_tier: "default" | "fast" }
             interface SpeechConfig { service_tier: "default" | "fast" }`,
    },
    {
      name: "does not erase nullability while looking for repeated domains",
      code: `${IMPORT}const ZOpenAIServiceTier = z.enum(["default", "fast"]);
             type OpenAIServiceTier = z.infer<typeof ZOpenAIServiceTier>;
             interface GlobalConfig { service_tier: "default" | "fast" | null }
             interface SpeechConfig { service_tier: "default" | "fast" | null }`,
    },
    `${IMPORT}const UserSchema = z.object({ id: z.string() });
     interface User { readonly id: string }`,
    `${IMPORT}const EventSchema = z.object({ createdAt: z.date() });
     interface Event { createdAt: CustomDate }`,
    `${IMPORT}const UserSchema = z.object({ tags: z.array(z.string()).readonly() });
     interface User { tags: readonly string[] }`,
    `${IMPORT}const UserSchema = z.object({ id: z.string(), deletedAt: z.string().nullable() });
     interface User { id: string; deletedAt: string }`,

    `${IMPORT}const UserSchema = z.object({ user_id: z.string(), name: z.string() });
     const UserCamel = UserSchema.transform((row) => ({ userId: row.user_id, name: row.name }));
     interface User { user_id: string; name: string }`,

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

    `${IMPORT}interface Base { createdAt: string }
     const UserSchema = z.object({ id: z.string() });
     interface User extends Base { id: string }`,
    {
      name: "does not report aliases that are not bare object literals",
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             type User = BaseUser & { id: string };`,
    },

    `${IMPORT}const RoleSchema = z.object({ id: z.string() });
     const UserSchema = z.object({ role: RoleSchema, backupRole: RoleSchema });
     interface User { role: Role; backupRole: Role }`,

    `const z = builder; const UserSchema = z.object({ id: z.string() });
     interface User { id: string }`,

    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      filename: "src/parse.test.ts",
    },
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      name: "does not report twins in generated files (cwd is the package root, not the file's directory)",
      filename: "src/generated/api.ts",
      cwd: process.cwd(),
    },
    {
      name: "does not report twins in story files",
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      filename: "src/User.stories.tsx",
    },

    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string }`,
      options: [{ ignoreTypeNames: ["^User$"] }],
    },
    {
      name: "handwritten-twin-dynamic-member",
      code: "import { z } from \"zod\"; const UserSchema = z[auditDynamicMember]({ id: z[auditDynamicMember]() }); interface User { id: string }",
      filename: "src/user.ts",
    },
  ],

  invalid: [
{"name":"matching-union","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed']); type State='ran'|'failed';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"matching-export","code":"import {z} from 'zod'; export const StateSchema=z.enum(['ran','failed']); export type State='ran'|'failed';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"reordered-union","code":"import {z} from 'zod'; const RuleExecutionStateSchema=z.enum(['ran','failed']); type RuleExecutionState='failed'|'ran';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"type-before-schema","code":"import {z} from 'zod'; type State='ran'|'failed'; const StateSchema=z.enum(['ran','failed']);","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"aliased-import","code":"import {z as schema} from 'zod'; const StateSchema=schema.enum(['ran','failed']); type State='ran'|'failed';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"namespace-import","code":"import * as schema from 'zod/v4'; const StateSchema=schema.enum(['ran','failed']); type State='ran'|'failed';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"const-array-wrapper","code":"import {z} from 'zod'; const StateSchema=z.enum(['ran','failed'] as const); type State='ran'|'failed';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
{"name":"literal-wrappers","code":"import {z} from 'zod'; const StateSchema=z.enum([('ran' as const),('failed' as const)]); type State='ran'|'failed';","output":null,"errors":[{"messageId":"handWrittenTwin"}]},
    { name: "preserves the sole local Date type binding inside a twin", code: "import { z } from \"zod\"; type Date = globalThis.Date; const EventSchema = z.object({ at: z.date() }); interface Event { at: Date }", output: null, errors: [{ messageId: "handWrittenTwin" }] },
    { name: "derives a twin with an independently exported Date type use", code: "import { z } from \"zod\"; export type Kept = Date; type Date = globalThis.Date; const EventSchema = z.object({ at: z.date() }); interface Event { at: Date }", output: "import { z } from \"zod\"; export type Kept = Date; type Date = globalThis.Date; const EventSchema = z.object({ at: z.date() }); type Event = z.infer<typeof EventSchema>;", errors: [{ messageId: "handWrittenTwin" }] },
    {name: "derives an unused private alias using the original namespace", code: "import * as schema from \"zod\"; const UserSchema = schema.object({ id: schema.string() }); type User = { id: string };", output: "import * as schema from \"zod\"; const UserSchema = schema.object({ id: schema.string() }); type User = schema.infer<typeof UserSchema>;", errors: [{messageId: "handWrittenTwin"}]},
    {name: "preserves referenced twin ownership", code: "import { z } from \"zod\"; const UserSchema = z.object({ id: z.string() }); interface User { id: string } declare const value: User;", output: null, errors: [{messageId: "handWrittenTwin"}]},
    {name: "preserves exported twin ownership", code: "import { z } from \"zod\"; const UserSchema = z.object({ id: z.string() }); export interface User { id: string }", output: null, errors: [{messageId: "handWrittenTwin"}]},
    {name: "preserves member documentation", code: "import { z } from \"zod\"; const UserSchema = z.object({ id: z.string() }); interface User { /** stable contract */ id: string }", output: null, errors: [{messageId: "handWrittenTwin"}]},
    { name: "reports the documented hand-written twin", code: HANDWRITTEN_TWIN_EXAMPLE, output: "import { z } from \"zod\"; const UserSchema = z.object({ id: z.string() }); type User = z.infer<typeof UserSchema>;", errors: [{ messageId: "handWrittenTwin", data: { typeName: "User", schemaName: "UserSchema" } }] },
    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
             interface User { id: string; name: string }`,
      output: `${IMPORT}const UserSchema = z.object({ id: z.string(), name: z.string() });
             type User = z.infer<typeof UserSchema>;`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "User", schemaName: "UserSchema" } }],
    },

    {
      code: `${IMPORT}export interface ApiConfig { type: string; endpoint?: string }
             export const apiConfigSchema = z.object({ type: z.string(), endpoint: z.string().optional() });`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "ApiConfig", schemaName: "apiConfigSchema" } }],
    },

    {
      code: `${IMPORT}const ZJobOptionsSchema = z.object({ id: z.string().optional(), name: z.string(), attempts: z.number() });
             type JobOptions = { id?: string; name: string; attempts: number };`,
      output: `${IMPORT}const ZJobOptionsSchema = z.object({ id: z.string().optional(), name: z.string(), attempts: z.number() });
             type JobOptions = z.infer<typeof ZJobOptionsSchema>;`,
      errors: [{ messageId: "handWrittenTwin", data: { typeName: "JobOptions", schemaName: "ZJobOptionsSchema" } }],
    },

    {
      code: `${IMPORT}const settingsSchema = z.object({ theme: z.string(), compact: z.boolean() });
             interface SettingsType { theme: string; compact: boolean }`,
      output: `${IMPORT}const settingsSchema = z.object({ theme: z.string(), compact: z.boolean() });
             type SettingsType = z.infer<typeof settingsSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },

    {
      code: `${IMPORT}const RowSchema = z.object({ id: z.string(), label: z.string().nullable(), note: z.string().optional() });
             interface Row { id: string; label: string | null; note?: string }`,
      output: `${IMPORT}const RowSchema = z.object({ id: z.string(), label: z.string().nullable(), note: z.string().optional() });
             type Row = z.infer<typeof RowSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },

    {
      code: `import * as zod from "zod";
             const eventSchema = zod.object({ kind: zod.literal("click"), at: zod.number() }).describe("an event");
             interface Event { kind: "click"; at: number }`,
      output: `import * as zod from "zod";
             const eventSchema = zod.object({ kind: zod.literal("click"), at: zod.number() }).describe("an event");
             type Event = zod.infer<typeof eventSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "reports twins behind shape-preserving schema chains",
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() }).refine((user) => user.id.length > 0).meta({ title: "User" });
             interface User { id: string }`,
      output: `${IMPORT}const UserSchema = z.object({ id: z.string() }).refine((user) => user.id.length > 0).meta({ title: "User" });
             type User = z.infer<typeof UserSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "reports a strictObject twin",
      code: `${IMPORT}const UserSchema = z.strictObject({ id: z.string(), active: z.boolean() });
             type User = { id: string; active: boolean };`,
      output: `${IMPORT}const UserSchema = z.strictObject({ id: z.string(), active: z.boolean() });
             type User = z.infer<typeof UserSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "compares exact enum values independent of order",
      code: `${IMPORT}const JobSchema = z.object({ state: z.enum(["queued", "running"]), id: z.string() });
             interface Job { state: "running" | "queued"; id: string }`,
      output: `${IMPORT}const JobSchema = z.object({ state: z.enum(["queued", "running"]), id: z.string() });
             type Job = z.infer<typeof JobSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "reuses an existing inferred enum type across repeated object fields",
      code: `${IMPORT}export const ZOpenAIServiceTier = z.enum(["default", "fast"]);
             export type OpenAIServiceTier = z.infer<typeof ZOpenAIServiceTier>;
             export interface GlobalConfig { service_tier: "default" | "fast" }
             export type SpeechConfig = { service_tier: "fast" | "default" };`,
      errors: [
        {
          messageId: "repeatedEnumUnion",
          data: {
            propertyName: "service_tier",
            schemaName: "ZOpenAIServiceTier",
            typeName: "OpenAIServiceTier",
          },
        },
      ],
    },
    {
      name: "reports a required output property supplied by a schema default",
      code: `${IMPORT}const UserSchema = z.object({ name: z.string().default("anonymous") });
             interface User { name: string }`,
      output: `${IMPORT}const UserSchema = z.object({ name: z.string().default("anonymous") });
             type User = z.infer<typeof UserSchema>;`,
      errors: [{ messageId: "handWrittenTwin" }],
    },

    {
      code: `${IMPORT}const UserSchema = z.object({ id: z.string() });
             interface User { id: string; nickname: string }`,
      options: [{ requireIdenticalShape: false }],
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "reports a twin whose member is the lib Date (no fix: Oxlint's scope manager has no lib globals)",
      code: `${IMPORT}const EventSchema = z.object({ createdAt: z.date() });
             interface Event { createdAt: Date }`,
      output: null,
      errors: [{ messageId: "handWrittenTwin" }],
    },
    {
      name: "handwritten-twin-static-member",
      code: "import { z } from \"zod\"; const UserSchema = z[\"object\"]({ id: z[\"string\"]() }); interface User { id: string }",
      filename: "src/user.ts",
      output: "import { z } from \"zod\"; const UserSchema = z[\"object\"]({ id: z[\"string\"]() }); type User = z.infer<typeof UserSchema>;",
      errors: [{ messageId: "handWrittenTwin" }],
    },
  ],
});
