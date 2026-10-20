import type { ESLint } from "eslint";

export default function eslintCompactFormatter(
  results: readonly ESLint.LintResult[],
): string {
  return JSON.stringify(
    results.map(({ filePath, messages }) => ({
      filePath,
      messages: messages.map((entry) => {
        const {
          ruleId,
          severity,
          fatal,
          message,
          line,
          column,
          endLine,
          endColumn,
        } = entry;
        return {
          ruleId,
          severity,
          fatal,
          message,
          line,
          column,
          endLine,
          endColumn,
          ...("sarjRequiredSourcePolicy" in entry &&
          entry.sarjRequiredSourcePolicy === true
            ? { sarjRequiredSourcePolicy: true }
            : {}),
        };
      }),
    })),
  );
}
