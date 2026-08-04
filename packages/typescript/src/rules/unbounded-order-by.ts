/**
 * @fileoverview unbounded-order-by — review a result sort that has no database row cap.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/unbounded-order-by.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import {
  createSqlListener,
  hasTopLevelPhrase,
  hasTopLevelRowCap,
  isRuntimeSqlNode,
} from "./_sql.js";

type MessageIds = "unboundedOrderBy";
type Options = readonly [];

const SELECT = /\bSELECT\b[\s\S]*?\bFROM\b/i;

export default createRule<Options, MessageIds>({
  name: "unbounded-order-by",
  meta: {
    type: "suggestion",
    docs: { description: "Warn when embedded SQL sorts a result without LIMIT or FETCH." },
    schema: [],
    messages: {
      unboundedOrderBy:
        "Result-level ORDER BY has no database row cap. Add LIMIT/keyset pagination, or document why the complete result is independently bounded.",
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
      if (!SELECT.test(sql) || !hasTopLevelPhrase(sql, "ORDER", "BY")) {
        return;
      }
      if (hasTopLevelRowCap(sql)) {
        return;
      }
      if (
        hasTopLevelPhrase(sql, "FOR", "UPDATE") ||
        hasTopLevelPhrase(sql, "FOR", "SHARE") ||
        hasTopLevelPhrase(sql, "FOR", "NO", "KEY", "UPDATE") ||
        hasTopLevelPhrase(sql, "FOR", "KEY", "SHARE")
      ) {
        return;
      }
      context.report({ node, messageId: "unboundedOrderBy" });
    });
  },
});
