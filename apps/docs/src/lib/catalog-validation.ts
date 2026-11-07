import { z } from "zod";

export const ENGINES = ["python", "oxlint", "iac", "sql", "text"] as const;

const TextSchema = z.string().min(1);
const FileSchema = z.object({ path: TextSchema, source: TextSchema });
export const ExampleSchema = z.object({
  id: TextSchema,
  scenarioId: TextSchema,
  title: TextSchema,
  outcome: z.enum(["accept", "reject"]),
  focusPath: TextSchema,
  expectedCount: z.number().int().nonnegative(),
  files: z.array(FileSchema).min(1),
  fixedFiles: z.array(FileSchema),
});
const RuleSchema = z.object({
  key: TextSchema,
  engine: z.enum(ENGINES),
  id: TextSchema,
  code: z.string().nullable(),
  summary: TextSchema,
  rationale: TextSchema,
  remediation: TextSchema,
  category: z.enum(["architecture", "correctness", "maintainability", "performance", "security", "style", "testing"]),
  languages: z.array(z.enum(["config", "iac", "markdown", "python", "shell", "sql", "typescript"])),
  defaultLevel: z.enum(["error", "off", "warning"]),
  autofix: z.enum(["none", "safe", "suggestion"]),
  status: z.literal("active"),
  aliases: z.array(z.string()),
  limitations: z.array(z.string()),
  filePatterns: z.array(z.string()),
  messageIds: z.array(z.string()),
  optionsSchema: z.record(z.string(), z.unknown()).nullable(),
  references: z.array(z.string().startsWith("https://")),
  since: z.string().nullable(),
  source: TextSchema,
  test: TextSchema,
  examples: z.array(ExampleSchema),
});
const CatalogSchema = z.object({ schemaVersion: z.literal(1), rules: z.array(RuleSchema) });

export type ExampleFile = z.infer<typeof FileSchema>;
export type RuleExample = z.infer<typeof ExampleSchema>;
export type Rule = z.infer<typeof RuleSchema>;
export type Catalog = z.infer<typeof CatalogSchema>;
export type Engine = Rule["engine"];
export type DefaultLevel = Rule["defaultLevel"];
export type Autofix = Rule["autofix"];
export type Category = Rule["category"];
export type Language = Rule["languages"][number];

export function validateCatalog(value: unknown): Catalog {
  if (!CatalogSchema.validate(value)) {
    const result = CatalogSchema.safeParse(value);
    throw new TypeError("rule catalog is invalid.", { cause: result.error });
  }
  const { rules } = value;
  const keys = new Set<string>();
  for (const [index, rule] of rules.entries()) {
    const context = `rule catalog rules[${String(index)}]`;
    if (rule.key !== `${rule.engine}:${rule.id}`) {
      throw new TypeError(`${context}.key must equal ${rule.engine}:${rule.id}.`);
    }
    validateScenarioPairs(rule.examples, context);
    if (keys.has(rule.key))
      throw new TypeError(`rule catalog contains duplicate key ${rule.key}.`);
    keys.add(rule.key);
  }
  const aliases = new Set<string>();
  for (const rule of rules) {
    for (const alias of rule.aliases) {
      const aliasKey = `${rule.engine}:${alias}`;
      if (keys.has(aliasKey))
        throw new TypeError(`rule alias ${aliasKey} shadows an active rule.`);
      if (aliases.has(aliasKey))
        throw new TypeError(`rule alias ${aliasKey} has multiple targets.`);
      aliases.add(aliasKey);
    }
  }
  return value;
}

function validateScenarioPairs(examples: RuleExample[], context: string): void {
  const scenarios = new Set(examples.map((example) => example.scenarioId));
  for (const scenario of scenarios) {
    const pair = examples.filter((example) => example.scenarioId === scenario);
    const outcomes = new Set(pair.map((example) => example.outcome));
    if (pair.length !== 2 || !outcomes.has("reject") || !outcomes.has("accept")) {
      throw new TypeError(
        `${context}.examples scenario ${scenario} must contain tested before and after source.`,
      );
    }
  }
}
