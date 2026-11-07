/**
 * @fileoverview store-insert-requires-on-conflict — a bare `INSERT` duplicates rows or throws under cron re-runs and queue redelivery.
 *
 * Port of the 18.x `store-insert-requires-on-conflict` rule. Untyped.
 */

import { defineRule, type ESTree, type Node } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isTestFile } from "../utils/paths.js";
import { createSqlListener } from "../utils/sql.js";

const NAME = "store-insert-requires-on-conflict";

/** Matches INSERT writes only when their SQL keywords are adjacent. */
const INSERT_WRITE =
  /\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w."'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b/i;

/** Matches conflict-policy syntax without proving replay safety. */
const CONFLICT_HANDLED = /\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b|\bINSERT\b[\s\S]*?\bSELECT\b[\s\S]*?\bWHERE\s+NOT\s+EXISTS\b/i;

const REPLAY_CONTRACT_NAME = /(?:enqueue|ensure|migrate|recordOnce|schedule|seed|upsert|getOrCreate|createIfAbsent|insertIfAbsent)/i;

function owningCallableName(node: Node): string | null {
  for (let current = parentOf(node); current !== null; current = parentOf(current)) {
    if (current.type === "FunctionDeclaration") {
      return current.id?.name ?? null;
    }
    if (current.type === "MethodDefinition") {
      return !current.computed && current.key.type === "Identifier" ? current.key.name : null;
    }
    if (current.type === "ArrowFunctionExpression" || current.type === "FunctionExpression") {
      return expressionCallableName(current);
    }
  }
  return null;
}

function expressionCallableName(current: ESTree.ArrowFunctionExpression | ESTree.Function): string | null {
  const parent = parentOf(current);
  if (parent?.type === "VariableDeclarator" && parent.id.type === "Identifier") return parent.id.name;
  if (parent?.type === "Property" && !parent.computed && parent.key.type === "Identifier") return parent.key.name;
  return parent?.type === "MethodDefinition" && !parent.computed && parent.key.type === "Identifier" ? parent.key.name : null;
}

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Review conflict handling for embedded inserts in replay-named callables.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      storeInsertRequiresOnConflict:
        "This INSERT is inside a replay-named callable without recognized conflict handling. Review duplicate execution, unique constraints, and the appropriate conflict policy for your SQL dialect.",
    },
  },
  createOnce(context) {
    const listener = createSqlListener((sql: string, node: Node): void => {
      if (!INSERT_WRITE.test(sql) || CONFLICT_HANDLED.test(sql)) return;
      const owner = owningCallableName(node);
      if (owner === null || !REPLAY_CONTRACT_NAME.test(owner)) return;
      context.report({ node, messageId: "storeInsertRequiresOnConflict" });
    });
    return {
      ...listener,
      before() {
        listener.before();
        return !isTestFile({ filename: context.filename, cwd: context.cwd });
      },
    };
  },
});
