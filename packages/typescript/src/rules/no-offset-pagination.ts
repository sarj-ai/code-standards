/**
 * @fileoverview no-offset-pagination — `OFFSET m` scans and discards m rows per page and shifts under concurrent writes, so rows repeat or vanish.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-offset-pagination.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "noOffsetPagination";
type Options = readonly [];

export const NO_OFFSET_PAGINATION_DOCUMENTATION = {
  summary: "Prefer keyset pagination for embedded SQL queries using OFFSET.",
  rationale: "Offset pagination scans skipped rows and shifts page boundaries under concurrent writes.",
  remediation: "Consider a keyset cursor that preserves the query's complete ordering, tie-breakers, and filters.",
  category: "performance",
  limitations: ["A SELECT/FROM query shape or adjacent LIMIT/OFFSET fragment is required. Isolated OFFSET fragments and test files are excluded; this lexical context does not prove a database execution sink. Performance and concurrent-write behavior depend on indexes, ordering, isolation, and dialect; bounded pages and random page access can justify OFFSET."],
  examples: [
    { id: "keyset-pagination", title: "Page from a stable cursor", outcome: "no-match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT id FROM runs WHERE id > ? ORDER BY id LIMIT ?`).all();" }], focusPath: "src/runs.ts", expectedCount: 0, public: true },
    { id: "offset-pagination", title: "Do not page by offset", outcome: "match", files: [{ path: "src/runs.ts", source: "db.query(`SELECT id FROM runs ORDER BY id LIMIT ? OFFSET ?`);" }], focusPath: "src/runs.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** Match pagination across the parameter styles supported by the TS, Python, and SQL rules. */
const OFFSET_PAGINATION = /\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)/i;

/** Cheap substring gate; noise-stripping can only ever remove keywords, never add them. */
const OFFSET_GATE = /offset/i;
const PAGINATION_CONTEXT = /\bSELECT\b[\s\S]*\bFROM\b[\s\S]*\bOFFSET\b|\bLIMIT\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)\s+OFFSET\b/i;

export default createRule<Options, MessageIds>({
  name: "no-offset-pagination",
  documentation: NO_OFFSET_PAGINATION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Prefer keyset pagination for embedded SQL queries using OFFSET.",
    },
    schema: [],
    messages: {
      noOffsetPagination:
        "Review OFFSET pagination for large or changing result sets. If a keyset cursor fits the access pattern, preserve the query's complete ordering, tie-breakers, and filters; bounded pages or random page access may justify OFFSET.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || !OFFSET_GATE.test(context.sourceCode.text)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node): void => {
      if (!PAGINATION_CONTEXT.test(sql) || !OFFSET_PAGINATION.test(sql)) {
        return;
      }
      context.report({ node, messageId: "noOffsetPagination" });
    });
  },
});
