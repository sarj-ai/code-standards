import { readFileSync } from "node:fs";

import { z } from "zod";

const WARNING_LIFECYCLE_SCHEMA = z.object({
  schemaVersion: z.literal(1),
  rules: z.array(z.string()),
}).strict();

export function warningStageEslintRules(): string[] {
  const path = new URL(
    "../../standards/src/sarj_standards/configs/rule-warning-levels.v1.json",
    import.meta.url,
  );
  const lifecycle = WARNING_LIFECYCLE_SCHEMA.parse(
    JSON.parse(readFileSync(path, "utf8")),
  );
  return lifecycle.rules
    .filter((rule) => rule.startsWith("eslint:"))
    .map((rule) => `@sarj/${rule.slice("eslint:".length)}`)
    .toSorted();
}

export function rulesOf(config: unknown): Record<string, unknown> {
  if (typeof config !== "object" || config === null || !("rules" in config)) return {};
  const { rules } = config;
  return typeof rules === "object" && rules !== null ? rules : {};
}
