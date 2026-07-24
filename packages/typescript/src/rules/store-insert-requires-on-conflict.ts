/**
 * @fileoverview TS port of SARJ018 (`store-insert-requires-on-conflict`).
 * An embedded `INSERT INTO ... VALUES/SELECT` with no conflict clause must
 * become an idempotent upsert.
 *
 * Store write paths run under retries, races, and replays — and on Cloudflare
 * Workers that is the *normal* case, not the exception: a cron trigger can fire
 * twice, a Queue message is redelivered on any handler throw, and a `waitUntil`
 * task can be retried after the response is already sent. A bare `INSERT` under
 * redelivery either duplicates rows (a second Slack post, a second email, a
 * double-counted referral) or throws on a unique-constraint violation, which
 * fails the handler, which triggers another redelivery. Every store write should
 * be `INSERT ... ON CONFLICT ... DO UPDATE` / `DO NOTHING` so replay is a no-op.
 *
 * The rule reads every statically-resolvable SQL string in the file — plain
 * literals, template literals (`${...}` becomes a `?` parameter marker), `+`
 * concatenations, and `[...].join(" ")` fragment arrays — and flags one that
 * contains a genuine `INSERT INTO ... VALUES` / `... SELECT` write with no
 * conflict handling. SQL string-literal values and `--` / comment bodies are
 * neutralized first, so an `ON CONFLICT` living inside a quoted value never
 * excuses a bare insert, a `--` inside a value never eats a real clause, and
 * commented-out keywords neither trigger nor excuse a finding.
 *
 * Deliberately NOT flagged:
 * - SQLite/D1's own idempotent insert forms: `INSERT OR IGNORE INTO ...` and
 *   `INSERT OR REPLACE INTO ...` already survive replay.
 * - MySQL's `ON DUPLICATE KEY UPDATE`, the same contract under another name.
 * - Pure reads, DDL, and `RETURNING`-only tails.
 * - Test files. A fresh in-memory D1 has nothing to conflict with, so fixture
 *   seeding legitimately uses a bare `INSERT`; flagging it would train people to
 *   ignore the rule.
 *
 * For a deliberate append-only write (an event/audit log where duplicates are
 * the point) disable with an inline `eslint-disable-next-line` and a reason.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "storeInsertRequiresOnConflict";
type Options = readonly [];

/**
 * A real insert *write*: the keyword, a table identifier, an optional column
 * list, then `VALUES` / `SELECT` / `DEFAULT VALUES` with nothing in between.
 * Requiring that exact adjacency is what keeps English prose out — "failed to
 * insert into the queue: values were rejected" has words between the table and
 * the verb, so it does not match. The optional `OR <action>` clause is SQLite's
 * conflict resolution; it is matched here so `INSERT OR IGNORE INTO` is
 * recognised as an insert at all, then excused below.
 */
const INSERT_WRITE =
  /\bINSERT\s+(?:OR\s+\w+\s+)?INTO\s+[\w."'`?$:@-]+\s*(?:\([^)]*\)\s*)?(?:VALUES|SELECT|DEFAULT\s+VALUES)\b/i;

/** Conflict handling that makes the write replay-safe. */
const CONFLICT_HANDLED = /\bON\s+CONFLICT\b|\bON\s+DUPLICATE\s+KEY\b|\bINSERT\s+OR\s+(?:IGNORE|REPLACE)\b/i;

/**
 * Cheap substring gate. Noise-stripping only ever blanks characters to spaces,
 * so it can never introduce a keyword the raw text lacks — a file with no
 * `insert` at all can never produce a finding, and most files in a repo sweep
 * are not SQL-bearing.
 */
const INSERT_GATE = /insert/i;

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
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
