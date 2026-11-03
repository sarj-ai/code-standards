import { z } from "zod";

import type { CliCommand, CliReference } from "./cli.ts";

const TextSchema = z.string().min(1);
const OptionSchema = z.object({
  kind: z.enum(["option", "positional"]),
  names: z.array(z.string()),
  metavar: z.string().nullable(),
  summary: z.string(),
  choices: z.array(z.string()),
  required: z.boolean(),
  repeatable: z.boolean(),
});
const CommandSchema: z.ZodType<CliCommand> = z.object({
  name: TextSchema,
  path: z.array(z.string()),
  usage: TextSchema,
  summary: z.string(),
  options: z.array(OptionSchema),
  commands: z.array(z.lazy(() => CommandSchema)),
});
const ReferenceSchema = z.object({
  schemaVersion: z.literal(1),
  version: TextSchema,
  program: TextSchema,
  summary: TextSchema,
  epilog: z.string().nullable(),
  globalOptions: z.array(OptionSchema),
  commands: z.array(CommandSchema),
  launcher: z.object({ install: TextSchema, runLatest: TextSchema }),
}) satisfies z.ZodType<CliReference>;

export function parseReference(value: unknown): z.output<typeof ReferenceSchema> {
  const result = ReferenceSchema.safeParse(value);
  if (!result.success) {
    throw new TypeError("CLI reference is invalid.", { cause: result.error });
  }
  return result.data;
}
