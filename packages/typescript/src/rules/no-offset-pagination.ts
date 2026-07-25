/**
 * @fileoverview TS port of SARJ025 (`no-offset-pagination`). `LIMIT n OFFSET m`
 * makes the database scan and discard every one of the `m` skipped rows before
 * returning the page, so page N costs O(N): deep pages get linearly slower until
 * they blow the request budget. Worse, under concurrent inserts the offset window
 * shifts between requests, so a row can be returned twice or skipped entirely —
 * a paginated backfill silently misses records. Keyset / cursor pagination
 * (`WHERE id > ? ORDER BY id LIMIT n`) is O(page) and stable.
 *
 * The rule reads statically-resolvable SQL strings (literals, template literals,
 * `+` concatenations, `[...].join(" ")` fragment arrays), neutralizes string
 * values and `--` / comment bodies first, and flags an `OFFSET` keyword
 * immediately followed by a value/param token — `?` or `?1` (SQLite/D1), `:name`,
 * `@name`, `$1`, or a bare digit. A `${...}` substitution has already become `?`
 * by then, so an interpolated offset is caught too.
 *
 * Requiring the value token is what keeps false positives at zero: it excludes
 * the English word ("offset out of range", "no base offset"), an `'offset'`
 * string value or object key, and array-index constructs like BigQuery's
 * `UNNEST(...) WITH OFFSET AS col`, none of which put a value after the keyword.
 *
 *     // flagged
 *     `SELECT id, status FROM runs ORDER BY created_at LIMIT ? OFFSET ?`
 *
 *     // preferred
 *     `SELECT id, status FROM runs WHERE id > ? ORDER BY id LIMIT ?`
 *
 * Test files are out of scope — a bounded fixture query is not a production
 * pagination path.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "noOffsetPagination";
type Options = readonly [];

/** `OFFSET` followed by a value/param token — the real pagination construct. */
const OFFSET_PAGINATION = /\bOFFSET\s+(?:\?\d*|:\w+|@\w+|\$\d+|\d+)/i;

/** Cheap substring gate; noise-stripping can only ever remove keywords, never add them. */
const OFFSET_GATE = /offset/i;

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
