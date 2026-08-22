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
  summary: "Disallow OFFSET pagination in embedded SQL; it is O(N) per page and drops or repeats rows under concurrent writes. Use a keyset cursor.",
  rationale: "Offset pagination scans skipped rows and shifts page boundaries under concurrent writes.",
  remediation: "Page with a stable ordered key and a cursor predicate.",
  category: "performance",
  limitations: ["Only embedded SQL is inspected; test files and non-pagination OFFSET syntax are excluded."],
  examples: [
    { id: "keyset-pagination", title: "Page from a stable cursor", outcome: "no-match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT id FROM runs WHERE id > ? ORDER BY id LIMIT ?`).all();" }], focusPath: "src/runs.ts", expectedCount: 0, public: true },
    { id: "offset-pagination", title: "Do not page by offset", outcome: "match", files: [{ path: "src/runs.ts", source: "db.query(`SELECT id FROM runs ORDER BY id LIMIT ? OFFSET ?`);" }], focusPath: "src/runs.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** Match pagination across the parameter styles supported by the TS, Python, and SQL rules. */
const OFFSET_PAGINATION = /\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)/i;

/** Cheap substring gate; noise-stripping can only ever remove keywords, never add them. */
const OFFSET_GATE = /offset/i;

export default createRule<Options, MessageIds>({
  name: "no-offset-pagination",
  documentation: NO_OFFSET_PAGINATION_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow OFFSET pagination in embedded SQL; it is O(N) per page and drops or repeats rows under concurrent writes. Use a keyset cursor.",
    },
    schema: [],
    messages: {
      noOffsetPagination:
        "OFFSET pagination scans and discards every skipped row (O(N) per page) and shifts under concurrent inserts, so rows get repeated or missed. Use a keyset cursor: `WHERE id > ? ORDER BY id LIMIT ?`.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || !OFFSET_GATE.test(context.sourceCode.text)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node): void => {
      if (!OFFSET_PAGINATION.test(sql)) {
        return;
      }
      context.report({ node, messageId: "noOffsetPagination" });
    });
  },
});
