import type { TSESLint } from "@typescript-eslint/utils";

/** Adapt immutable rule metadata to ESLint's mutable configuration tuple. */
export function eslintRuleSetting(
  value: unknown,
): TSESLint.FlatConfig.RuleEntry {
  if (isLevel(value)) return value;
  const options: readonly unknown[] | null = Array.isArray(value) ? value : null;
  if (options !== null && isLevel(options[0]))
    return [options[0], ...options.slice(1)];
  throw new TypeError(
    "ESLint rule setting requires a severity or severity/options tuple",
  );
}

function isLevel(
  value: unknown,
) {
  return (
    value === 0 ||
    value === 1 ||
    value === 2 ||
    value === "off" ||
    value === "warn" ||
    value === "error"
  );
}
