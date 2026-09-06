/**
 * @fileoverview store-insert-requires-on-conflict — a bare `INSERT` duplicates rows or throws under cron re-runs and queue redelivery.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/store-insert-requires-on-conflict.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "storeInsertRequiresOnConflict";
type Options = readonly [];

export const STORE_INSERT_REQUIRES_ON_CONFLICT_DOCUMENTATION = {
  summary: "Review conflict handling for embedded inserts in replay-named callables.",
  rationale: "Names such as seed, enqueue, or upsert suggest that repeated execution deserves a conflict-policy review, but do not prove a replay contract.",
  remediation: "Choose conflict handling appropriate to the schema and SQL dialect, or document why this insertion must fail on a duplicate.",
  category: "correctness",
  limitations: ["Only the nearest statically named callable is considered; top-level inserts and anonymous callbacks are excluded. Recognized conflict syntax does not prove idempotence or concurrency safety: WHERE NOT EXISTS can race, and INSERT OR REPLACE can delete an existing row. Review unique constraints and dialect semantics manually."],
  examples: [
    { id: "conflict-safe-insert", title: "Review the conflict policy for a replayed insert", outcome: "no-match", files: [{ path: "src/store.ts", source: "function seed() { db.prepare(`INSERT INTO runs (id) VALUES (?) ON CONFLICT(id) DO NOTHING`).run(); }" }], focusPath: "src/store.ts", expectedCount: 0, public: true },
    { id: "bare-insert", title: "Review a bare insert in a replay-named callable", outcome: "match", files: [{ path: "src/store.ts", source: "function seed() { db.prepare(`INSERT INTO runs (id) VALUES (?)`).run(); }" }], focusPath: "src/store.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** Matches INSERT writes only when their SQL keywords are adjacent. */
const INSERT_WRITE =
  /\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w."'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b/i;

/** Matches conflict-policy syntax without proving replay safety. */
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
      return !current.computed && current.key.type === "Identifier" ? current.key.name : null;
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
      !current.parent.computed &&
      current.parent.key.type === "Identifier"
    ) {
      return current.parent.key.name;
    }
    if (current.type === "ArrowFunctionExpression" || current.type === "FunctionExpression") {
      const parent = current.parent;
      return parent.type === "MethodDefinition" && !parent.computed && parent.key.type === "Identifier" ? parent.key.name : null;
    }
  }
  return null;
}

const INSERT_GATE = /insert/i;

export default createRule<Options, MessageIds>({
  name: "store-insert-requires-on-conflict",
  documentation: STORE_INSERT_REQUIRES_ON_CONFLICT_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Review conflict handling for embedded inserts in replay-named callables.",
    },
    schema: [],
    messages: {
      storeInsertRequiresOnConflict:
        "This INSERT is inside a replay-named callable without recognized conflict handling. Review duplicate execution, unique constraints, and the appropriate conflict policy for your SQL dialect.",
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
      if (owner === null || !REPLAY_CONTRACT_NAME.test(owner)) {
        return;
      }
      context.report({ node, messageId: "storeInsertRequiresOnConflict" });
    });
  },
});
