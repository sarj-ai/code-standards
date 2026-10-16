import type { ESLint } from "eslint";

export default function eslintCompactFormatter(
  results: readonly ESLint.LintResult[],
): string {
  return JSON.stringify(
    results.map(({ filePath, messages }) => ({
      filePath,
      messages: messages.map(
        ({
          ruleId,
          severity,
          fatal,
          message,
          line,
          column,
          endLine,
          endColumn,
        }) => ({
          ruleId,
          severity,
          fatal,
          message,
          line,
          column,
          endLine,
          endColumn,
        }),
      ),
    })),
  );
}
