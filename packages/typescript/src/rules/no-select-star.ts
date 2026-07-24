/**
 * @fileoverview TS port of SARJ021 (`no-select-star`). `SELECT *` over-fetches
 * every column (including large JSON/text blobs the caller never reads) and,
 * more importantly, makes the row shape implicit: the moment a column is added,
 * renamed, or reordered, the zod schema that parses the row starts failing — or
 * worse, silently accepts extra keys — and nothing in the query says which
 * columns the code actually depends on. Naming the columns makes the dependency
 * explicit and pins the row contract at the query.
 *
 * The rule reads statically-resolvable SQL strings (literals, template literals,
 * `+` concatenations, `[...].join(" ")` fragment arrays), neutralizes string
 * values and `--` / comment bodies first (so a `'*'` value is never mistaken for
 * a star), and flags a query — a string with a real `SELECT ... FROM` shape —
 * whose projection list holds a `*` in any position: bare (`SELECT *`,
 * `SELECT id, *`) or qualified (`c.*`, `main.runs.*`).
 *
 * Deliberately NOT flagged, matching the Python rule's tuning:
 * - `COUNT(*)` and other aggregate stars — the star is a function argument, not
 *   a projection.
 * - `a * b` arithmetic — an operand follows the star.
 * - `EXISTS (SELECT * ...)` — the projection is unused by definition.
 * - Prose that merely contains the words "select" and "from".
 * - Test files, where a `SELECT *` assertion over a fixture table is fine.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "noSelectStar";
type Options = readonly [];

/** A real SQL query shape, so prose containing the bare word "from" isn't matched. */
const QUERY_SHAPE = /\bSELECT\b[\s\S]*?\bFROM\b/i;
const SELECT_KEYWORD = /\bSELECT\b/gi;
const FROM_KEYWORD = /^FROM\b/i;
const EXISTS_BEFORE = /\bEXISTS\s*\(\s*$/i;
/** A `word.` immediately preceding a `*` marks a qualified star (`c.*`, `main.runs.*`). */
const QUALIFIED_PREFIX = /\w\.$/;

/** Cheap substring gate; a file with no star and no SELECT can never produce a finding. */
const SELECT_GATE = /select/i;

/**
 * True when the `*` at `pos` is a column-projection star.
 *
 * A projection star expands columns: bare (`SELECT *`, `id, *`) or qualified
 * (`c.*`). It is NOT a `COUNT(*)` argument (parenthesised on both sides) nor an
 * `a * b` multiply (an operand follows rather than a terminator).
 */
function isProjectionStar(sql: string, pos: number): boolean {
  if (QUALIFIED_PREFIX.test(sql.slice(0, pos))) {
    return true;
  }
  let before = pos - 1;
  while (before >= 0 && /\s/.test(sql[before] ?? "")) {
    before -= 1;
  }
  let after = pos + 1;
  while (after < sql.length && /\s/.test(sql[after] ?? "")) {
    after += 1;
  }
  const beforeChar = before >= 0 ? (sql[before] ?? "") : "";
  const afterChar = after < sql.length ? (sql[after] ?? "") : "";
  const terminates =
    afterChar === "" || afterChar === "," || afterChar === ")" || FROM_KEYWORD.test(sql.slice(after));
  if (!terminates) {
    return false;
  }
  return !(beforeChar === "(" && afterChar === ")");
}

/** True when the query projects a star that is not inside an `EXISTS (...)` subquery. */
function hasRealSelectStar(sql: string): boolean {
  const selects = [...sql.matchAll(SELECT_KEYWORD)].map((m) => m.index);
  for (let pos = 0; pos < sql.length; pos++) {
    if (sql[pos] !== "*" || !isProjectionStar(sql, pos)) {
      continue;
    }
    const owning = selects.filter((start) => start < pos).at(-1);
    if (owning !== undefined && !EXISTS_BEFORE.test(sql.slice(0, owning))) {
      return true;
    }
  }
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-select-star",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow SELECT * in embedded SQL; it over-fetches and leaves the row contract implicit, so a schema change breaks row parsing silently.",
    },
    schema: [],
    messages: {
      noSelectStar:
        "`SELECT *` over-fetches and leaves the row shape implicit — a new or reordered column silently changes what this query returns. List the columns explicitly.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || !SELECT_GATE.test(context.sourceCode.text)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node): void => {
      if (!QUERY_SHAPE.test(sql) || !hasRealSelectStar(sql)) {
        return;
      }
      context.report({ node, messageId: "noSelectStar" });
    });
  },
});
