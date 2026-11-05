import { createRequire } from "node:module";
import { resolve } from "node:path";

// Helpers ship in the Python wheel; resolve runtime peers from the consumer.
const require = createRequire(resolve("package.json"));
const { z } = require("zod") as typeof import("zod");

const TextSchema = z.string().min(1);
const StringsSchema = z.array(z.string());
const OptionalStringsSchema = z.preprocess((value) => value ?? [], StringsSchema);
const FlagSchema = z.boolean().catch(false);

export const RuleExecutionStateSchema = z.enum([
  "ran", "skipped", "untracked", "failed", "disabled", "ignored",
]);

export const FileExecutionSchema = z.object({
  ruleId: TextSchema,
  filePath: TextSchema.transform((value) => resolve(value)),
  execution: RuleExecutionStateSchema,
  requiresTypeInformation: z.boolean().nullable(),
  reason: TextSchema.optional(),
}).transform(({ reason, ...row }) => ({
  ...row,
  ...(reason === undefined ? {} : { reason }),
}));

export const FileExecutionsSchema = z.array(FileExecutionSchema);
export const DeclaredRequirementSchema = z.boolean().nullable().catch(null);
// Validate the capability without wrapping it, preserving its identity and receiver.
export const CallableSchema = z.function();

export const SelectedRequestSchema = z.object({
  full: FlagSchema,
  consoleOutput: FlagSchema,
  failOnWarnings: FlagSchema,
  rules: StringsSchema,
  config: z.string().nullable(),
  suppressionsLocation: z.string().nullable().default(null),
  upstreamRules: OptionalStringsSchema,
  upstreamAdvisories: OptionalStringsSchema,
  passOnUnpruned: FlagSchema,
});

export const SuppressionsSchema = z.record(z.string(), z.record(z.string(),
  z.object({ count: z.number().int().nonnegative() }),
));
