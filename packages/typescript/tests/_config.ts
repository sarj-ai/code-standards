import { rules } from "../src/index.js";
import { z } from "zod";

export function warningStageEslintRules(): string[] {
  return Object.entries(rules)
    .filter(([, rule]) => rule.documentation?.defaultLevel === "warning")
    .map(([ruleId]) => `@sarj/${ruleId}`)
    .toSorted();
}

export function rulesOf(config: unknown): Record<string, unknown> {
  const result = z.object({ rules: z.record(z.string(), z.unknown()) }).safeParse(config);
  return result.success ? result.data.rules : {};
}
