export function rulesOf(config: unknown): Record<string, unknown> {
  if (typeof config !== "object" || config === null || !("rules" in config)) return {};
  const { rules } = config;
  return typeof rules === "object" && rules !== null ? rules : {};
}
