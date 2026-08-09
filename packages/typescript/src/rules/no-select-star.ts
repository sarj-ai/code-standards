/**
 * @fileoverview no-select-star — `SELECT *` over-fetches and leaves the row contract implicit, so a schema change breaks row parsing silently.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-select-star.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener } from "./_sql.js";

type MessageIds = "noSelectStar";
type Options = readonly [];

export const noSelectStarDocumentation = {
  summary: "Disallow SELECT * in embedded SQL; it over-fetches and leaves the row contract implicit, so a schema change breaks row parsing silently.",
  rationale: "Wildcard projections couple row shape and query cost to unrelated schema changes.",
  remediation: "List every required column explicitly in the projection.",
  category: "correctness",
  limitations: ["Only statically visible embedded SQL is checked; function arguments such as COUNT(*) and stars inside EXISTS are excluded."],
  examples: [
    { id: "explicit-projection", title: "Select the required columns", outcome: "no-match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT id, status FROM runs`).all();" }], focusPath: "src/runs.ts", expectedCount: 0, public: true },
    { id: "wildcard-projection", title: "Do not select every column", outcome: "match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT * FROM runs`).all();" }], focusPath: "src/runs.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** A real SQL query shape, so prose containing the bare word "from" isn't matched. */
const QUERY_SHAPE = /\bSELECT\b[\s\S]*?\bFROM\b/i;
const SELECT_KEYWORD = /\bSELECT\b/gi;
const FROM_KEYWORD = /^FROM\b/i;
const EXISTS_BEFORE = /\bEXISTS\s*\(\s*$/i;
/** A `word.` immediately preceding a `*` marks a qualified star (`c.*`, `main.runs.*`). */
const QUALIFIED_PREFIX = /\w\.$/;

const SELECT_GATE = /select/i;

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

export default createRule<Options, MessageIds>({
  name: "no-select-star",
  documentation: noSelectStarDocumentation,
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
