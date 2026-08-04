/**
 * @fileoverview limit-requires-order-by — a row-limited SELECT needs a deterministic result order.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/limit-requires-order-by.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener, hasTopLevelPhrase, isRuntimeSqlNode } from "./_sql.js";

type MessageIds = "limitRequiresOrderBy";
type Options = readonly [];

const SELECT = /\bSELECT\b[\s\S]*?\bFROM\b/i;
export default createRule<Options, MessageIds>({
  name: "limit-requires-order-by",
  meta: {
    type: "suggestion",
    docs: { description: "Require deterministic ordering for multi-row-limited embedded SQL SELECTs." },
    schema: [],
    messages: {
      limitRequiresOrderBy:
        "Row-limited SELECT has no result-level ORDER BY, so the chosen rows are unstable. Order by a deterministic key.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node): void => {
      if (!isRuntimeSqlNode(node)) {
        return;
      }
      const limited =
        hasTopLevelPhrase(sql, "LIMIT") ||
        hasTopLevelPhrase(sql, "FETCH", "FIRST") ||
        hasTopLevelPhrase(sql, "FETCH", "NEXT");
      if (!limited || !SELECT.test(sql) || hasTopLevelPhrase(sql, "ORDER", "BY")) {
        return;
      }
      context.report({ node, messageId: "limitRequiresOrderBy" });
    });
  },
});
