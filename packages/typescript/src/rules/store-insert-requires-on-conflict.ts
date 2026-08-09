/**
 * @fileoverview store-insert-requires-on-conflict — a bare `INSERT` duplicates rows or throws under cron re-runs and queue redelivery.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/store-insert-requires-on-conflict.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "storeInsertRequiresOnConflict";
type Options = readonly [];

export const storeInsertRequiresOnConflictDocumentation = {
  summary: "Require embedded inserts in explicitly replayable callables to carry conflict handling.",
  rationale: "A callable named as an enqueue, seed, migration, schedule, ensure, or upsert promises replay safety.",
  remediation: "Add an appropriate `ON CONFLICT` action or supported replay-safe insert form.",
  category: "correctness",
  examples: [
    { id: "conflict-safe-insert", title: "Handle a replayed insert", outcome: "no-match", files: [{ path: "src/store.ts", source: "db.prepare(`INSERT INTO runs (id) VALUES (?) ON CONFLICT(id) DO NOTHING`).run();" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
    { id: "bare-insert", title: "Do not issue a replay-unsafe insert", outcome: "match", files: [{ path: "src/store.ts", source: "db.prepare(`INSERT INTO runs (id) VALUES (?)`).run();" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** Matches INSERT writes only when their SQL keywords are adjacent. */
const INSERT_WRITE =
  /\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w."'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b/i;

/** Matches supported replay-safe insert forms. */
const CONFLICT_HANDLED = /\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b|\bINSERT\b[\s\S]*?\bSELECT\b[\s\S]*?\bWHERE\s+NOT\s+EXISTS\b/i;

const REPLAY_CONTRACT_NAME = /(?:enqueue|ensure|migrate|recordOnce|schedule|seed|upsert|getOrCreate|createIfAbsent|insertIfAbsent)/i;

function owningCallableName(node: TSESTree.Node): string | null {
  for (
    let current: TSESTree.Node | null | undefined = node.parent;
    current !== null && current !== undefined;
    current = current.parent
  ) {
    if (current.type === "FunctionDeclaration") {
      return current.id?.name ?? null;
    }
    if (current.type === "MethodDefinition") {
      return current.key.type === "Identifier" ? current.key.name : null;
    }
    if (
      (current.type === "ArrowFunctionExpression" ||
        current.type === "FunctionExpression") &&
      current.parent.type === "VariableDeclarator" &&
      current.parent.id.type === "Identifier"
    ) {
      return current.parent.id.name;
    }
    if (
      (current.type === "ArrowFunctionExpression" ||
        current.type === "FunctionExpression") &&
      current.parent.type === "Property" &&
      current.parent.key.type === "Identifier"
    ) {
      return current.parent.key.name;
    }
  }
  return null;
}

const INSERT_GATE = /insert/i;

export default createRule<Options, MessageIds>({
  name: "store-insert-requires-on-conflict",
  documentation: storeInsertRequiresOnConflictDocumentation,
  meta: {
    type: "problem",
    docs: {
      description:
        "Require embedded inserts in explicitly replayable callables to carry conflict handling.",
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
      const owner = owningCallableName(node);
      if (owner !== null && !REPLAY_CONTRACT_NAME.test(owner)) {
        return;
      }
      context.report({ node, messageId: "storeInsertRequiresOnConflict" });
    });
  },
});
