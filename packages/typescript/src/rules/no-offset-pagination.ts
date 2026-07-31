/**
 * @fileoverview no-offset-pagination — `OFFSET m` scans and discards m rows per page and shifts under concurrent writes, so rows repeat or vanish.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-offset-pagination.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-offset-pagination.md
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "noOffsetPagination";
type Options = readonly [];

/**
 * `OFFSET` followed by a value or param token — the real pagination construct.
 * The parameter alternatives are the UNION of every marker the three packages
 * see, and are kept identical in SARJ025 and SARJ107.
 */
const OFFSET_PAGINATION = /\bOFFSET\s+(?:%s|%\(\w+\)s|\?\d*|:\w+|@\w+|\$\d+|\d+)/i;

/** Cheap substring gate; noise-stripping can only ever remove keywords, never add them. */
const OFFSET_GATE = /offset/i;

export default createRule<Options, MessageIds>({
  name: "no-offset-pagination",
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
