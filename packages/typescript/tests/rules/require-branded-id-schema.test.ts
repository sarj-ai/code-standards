import rule from "../../src/rules/require-branded-id-schema.js";
import { ruleTester } from "./_tester.js";

const unbrandedIdSchema = { messageId: "unbrandedIdSchema" } as const;
const mixedBrandedIds = { messageId: "mixedBrandedIds" } as const;
const interchangeableIdSchemas = { messageId: "interchangeableIdSchemas" } as const;
const zod = (code: string): string => `import { z } from 'zod';\n${code}`;

ruleTester().run("require-branded-id-schema", rule, {
  valid: [
    { code: zod("const DealIdSchema = z.string().min(1).max(256).brand<'CalAttioDealId'>();") },
    { code: zod("z.strictObject({ recordId: DealIdSchema, name: z.string() });") },
    { code: zod("const RequestIdSchema = z.uuid(); const IdSchema = z.string();") },
    { code: zod("z.object({ accountId: z.string(), label: z.string(), count: z.number() });") },
    { code: zod("z.object({ accountId: z.string(), teamId: z.number(), trace_id: z.string() });") },
    { code: zod("z.object({ accountId: z.string(), account_id: z.uuid() });") },
    { code: zod("z.object({ userId: UserIdSchema, user_id: z.string() });") },
    { code: zod("z.object({ accountId: z.string().pipe(z.uuid().brand<'AccountId'>()), teamId: z.uuid() });") },
    { code: zod("z.object({ accountId: z.string().array(), teamId: z.uuid() });") },
    { code: zod("z.object({ accountId: z.uuid(), teamId: z.uuid(), ...shape });") },
    { code: zod("z.object({ accountId: z.uuid(), ['teamId']: z.uuid() });") },
    { code: zod("z.object({ accountId: z.uuid(), teamId: z.uuid(), accountId: AccountId });") },
    { code: zod("let AccountIdSchema = z.uuid(); function f() { const TeamIdSchema = z.uuid(); }") },
    { code: zod("function f(z: Other) { return z.object({ accountId: z.string(), teamId: z.string() }); }") },
    { code: "const z = makeSchemaBuilder(); const AccountIdSchema = z.string();" },
    { code: "import { z } from './schema'; const AccountIdSchema = z.string();" },
    { code: "import { type z } from 'zod'; const AccountIdSchema = z.string();" },
    { code: "type RequestId = string; type Id = string; type TargetId = 'primary' | 'secondary'; type UserId = z.output<typeof UserIdSchema>;" },
    { filename: "src/generated/client.ts", code: zod("const AccountIdSchema = z.uuid();") },
    { filename: "src/ids.ts", code: "// @generated\nexport type AccountId = string;" },
  ],
  invalid: [
    {
      name: "reports a stand-alone UUID schema",
      code: zod("const ScenarioIdSchema = z.uuid();"),
      output: null,
      errors: [unbrandedIdSchema],
    },
    {
      name: "reports an exported scalar schema with an aliased factory",
      code: "import { number as scalar } from 'zod/v4'; export const TeamIdSchema = scalar().int().positive();",
      errors: [unbrandedIdSchema],
    },
    {
      name: "reports direct primitive aliases without a Zod import",
      code: "export type PermissionId = string; type SequenceId = number; type LegacyId = string | number;",
      errors: [unbrandedIdSchema, unbrandedIdSchema, unbrandedIdSchema],
    },
    {
      name: "reports mixed branding once even when two raw IDs also share a carrier",
      code: zod("z.object({ taskId: z.string().min(1).brand<'MediaProcessingTask'>(), videoId: z.string().min(1), sourceAudioFileId: z.string().min(1) });"),
      output: null,
      errors: [mixedBrandedIds],
    },
    {
      name: "recognizes a named schema reference as a brand signal",
      code: "import * as schema from 'zod/v4'; import { TaskIdSchema } from './ids'; schema.looseObject({ task_id: TaskIdSchema, 'video_id': schema.guid() });",
      errors: [mixedBrandedIds],
    },
    {
      name: "reports the second interchangeable field",
      code: zod("z.strictObject({\n  takeId: z.uuid(),\n  sessionId: z.uuid(),\n  clipId: z.string()\n});"),
      output: null,
      errors: [{ ...interchangeableIdSchemas, line: 4, column: 3 }],
    },
    {
      name: "groups string formats and keeps fields after a spread",
      code: "import { z as schema } from 'zod'; schema.object({ ...shape, accountId: schema.guid(), userId: schema.string().min(1).optional() });",
      errors: [interchangeableIdSchemas],
    },
    {
      name: "groups numeric identifiers independently",
      code: "import { object, number, z } from 'zod'; object({ taskId: number().int(), userId: z.uuid(), videoId: number() });",
      errors: [interchangeableIdSchemas],
    },
  ],
});
