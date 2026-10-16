import type { TSESLint } from "@typescript-eslint/utils";

/** Adapt immutable rule metadata to ESLint's mutable configuration tuple. */
export function eslintRuleSetting(
  value: unknown,
): TSESLint.FlatConfig.RuleEntry {
  if (isLevel(value)) return value;
  if (isOptions(value) && isLevel(value[0]))
    return [value[0], ...value.slice(1)];
  throw new TypeError(
    "ESLint rule setting requires a severity or severity/options tuple",
  );
}

function isOptions(value: unknown): value is readonly unknown[] {
  return Array.isArray(value);
}

function isLevel(
  value: unknown,
): value is 0 | 1 | 2 | "off" | "warn" | "error" {
  return (
    value === 0 ||
    value === 1 ||
    value === 2 ||
    value === "off" ||
    value === "warn" ||
    value === "error"
  );
}
