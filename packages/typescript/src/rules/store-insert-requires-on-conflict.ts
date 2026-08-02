/**
 * @fileoverview store-insert-requires-on-conflict — a bare `INSERT` duplicates rows or throws under cron re-runs and queue redelivery.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/store-insert-requires-on-conflict.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "storeInsertRequiresOnConflict";
type Options = readonly [];

/** Matches INSERT writes only when their SQL keywords are adjacent. */
const INSERT_WRITE =
  /\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w."'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b/i;

/** Matches supported replay-safe insert forms. */
const CONFLICT_HANDLED = /\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b/i;

const INSERT_GATE = /insert/i;

export default createRule<Options, MessageIds>({
  name: "store-insert-requires-on-conflict",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require an embedded SQL INSERT to carry ON CONFLICT; store writes replay under cron re-runs and queue redelivery and must be idempotent upserts.",
    },
    schema: [],
    messages: {
      storeInsertRequiresOnConflict:
        "This INSERT is not replay-safe: a cron re-run or queue redelivery duplicates the row (or fails the handler on a unique-constraint violation). Add `ON CONFLICT (...) DO UPDATE` / `DO NOTHING` (or `INSERT OR IGNORE`).",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || !INSERT_GATE.test(context.sourceCode.text)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node): void => {
      if (!INSERT_WRITE.test(sql) || CONFLICT_HANDLED.test(sql)) {
        return;
      }
      context.report({ node, messageId: "storeInsertRequiresOnConflict" });
    });
  },
});
