import { rules } from "../src/index.js";

export function warningStageEslintRules(): string[] {
  return Object.entries(rules)
    .filter(([, rule]) => rule.documentation?.defaultLevel === "warning")
    .map(([ruleId]) => `@sarj/${ruleId}`)
    .toSorted();
}

export function rulesOf(config: unknown): Record<string, unknown> {
  if (typeof config !== "object" || config === null || !("rules" in config)) return {};
  const { rules } = config;
  return typeof rules === "object" && rules !== null ? rules : {};
}
