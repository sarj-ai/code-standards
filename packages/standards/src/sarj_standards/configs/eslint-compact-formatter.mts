import type { ESLint } from "eslint";
import type { RuleExecutionSummary } from "./eslint-rule-execution.mts";

export default function eslintCompactFormatter(
  results: readonly ESLint.LintResult[],
): string {
  return JSON.stringify(compactResults(results));
}

export function formatWithRuleExecutions(
  results: readonly ESLint.LintResult[],
  ruleExecutions: readonly RuleExecutionSummary[],
): string {
  return JSON.stringify({ results: compactResults(results), ruleExecutions });
}

function compactResults(results: readonly ESLint.LintResult[]) {
  return results.map(({ filePath, messages }) => ({
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
    }));
}
