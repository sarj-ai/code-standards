/**
 * @fileoverview no-select-star — `SELECT *` over-fetches and leaves the row contract implicit, so a schema change breaks row parsing silently.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-select-star.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";
import { createSqlListener, stripSqlNoise } from "./_sql.js";

type MessageIds = "noSelectStar";
type Options = readonly [];

export const NO_SELECT_STAR_DOCUMENTATION = {
  summary: "Prefer explicit column projections over SELECT * in embedded SQL.",
  rationale: "Wildcard projections couple row shape and query cost to unrelated schema changes.",
  remediation: "List every required column explicitly in the projection.",
  category: "correctness",
  limitations: ["Only statically visible embedded SQL is checked; quoted strings (including PostgreSQL dollar strings), comments, function arguments such as COUNT(*), and stars inside EXISTS are excluded. Escaped ordinary strings, brackets, and backticks are handled conservatively. This is a bounded lexical scan, not a complete SQL parser."],
  examples: [
    { id: "explicit-projection", title: "Select the required columns", outcome: "no-match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT id, status FROM runs`).all();" }], focusPath: "src/runs.ts", expectedCount: 0, public: true },
    { id: "wildcard-projection", title: "Do not select every column", outcome: "match", files: [{ path: "src/runs.ts", source: "db.prepare(`SELECT * FROM runs`).all();" }], focusPath: "src/runs.ts", expectedCount: 1, public: true },
    { id: "decoded-query", scenarioId: "native-decoded-sql", title: "Inspect native-decoded query text", outcome: "match", files: [{ path: "src/page.ts", source: "db.query(\"SEL\\u0045CT * FROM runs\");" }], focusPath: "src/page.ts", expectedCount: 1, public: true },
    { id: "decoded-comment-data", scenarioId: "native-decoded-sql", title: "Ignore native-decoded comment data", outcome: "no-match", files: [{ path: "src/page.ts", source: "db.query(\"SEL\\x45CT id FROM runs /* SELECT * FROM runs */\");" }], focusPath: "src/page.ts", expectedCount: 0, public: true },
    {"id": "wrapped-exists-outer-wildcard", "scenarioId": "projection-owner", "title": "The outer projection still selects every column", "outcome": "match", "files": [{"path": "src/queries.ts", "source": "db.query(\"SELECT EXISTS((SELECT * FROM jobs)), * FROM runs\");"}], "focusPath": "src/queries.ts", "expectedCount": 1, "public": true},
    {"id": "quoted-column-arithmetic", "scenarioId": "projection-owner", "title": "Quoted arithmetic operands are not wildcards", "outcome": "no-match", "files": [{"path": "src/queries.ts", "source": "db.query(\"SELECT \\\"units\\\" * \\\"price\\\" AS total FROM entries\");"}], "focusPath": "src/queries.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;

/** A real SQL query shape, so prose containing the bare word "from" isn't matched. */
const QUERY_SELECT = /\bSELECT\b/i;
const QUERY_FROM = /\bFROM\b/i;
const SQL_TOKEN = /[A-Za-z_\u0080-\u{10FFFF}][A-Za-z0-9_$\u0080-\u{10FFFF}]*|\d+(?:\.\d+)?|\.[ \t\r\n\f\v]*\[(?:[^\]]|\]\])*\]|[-+*/<>=~!@#%^&|\x60?]+|[(),.;]/gu;
const ASCII_WORD = /^[A-Za-z_]+$/u;
const AMBIGUOUS_QUOTING = /[\x60[\]\\]/u;
const CONSERVATIVE_SELECT = /\bSELECT\b/gi;
const CONSERVATIVE_FROM = /FROM\b/iy;
const ASCII_IDENTIFIER_CHARACTER = /[A-Za-z0-9_]/u;
const SQL_WHITESPACE = /\s/u;
const EXISTS_KEYWORD_LENGTH = 6;
const PROJECTION_END = /\s*(?:[,)]|FROM(?![A-Za-z0-9_$\u0080-\u{10FFFF}])|$)/iyu;
const SELECT_PREFIX_WORDS: ReadonlySet<string> = new Set([
  "ALL", "DISTINCT", "HIGH_PRIORITY", "PERCENT", "SQL_BIG_RESULT", "SQL_BUFFER_RESULT",
  "SQL_CACHE", "SQL_CALC_FOUND_ROWS", "SQL_NO_CACHE", "SQL_SMALL_RESULT", "STRAIGHT_JOIN",
  "TIES", "TOP", "WITH",
]);

interface ConservativeSelect {
  readonly offset: number;
  readonly allowsStar: boolean;
}

interface ConservativeSql {
  readonly source: string;
  readonly selects: readonly ConservativeSelect[];
}

interface Projection {
  readonly exists: boolean;
  readonly strictSuffix: boolean;
  readonly conservative: ConservativeSql | undefined;
  readonly prefix: string[];
  star: boolean;
}

/** Keep the prefilter linear; projection ownership validates keyword order. */
function hasQueryShape(sql: string): boolean {
  return QUERY_SELECT.test(sql) && QUERY_FROM.test(sql);
}

/** Track projection ownership at each SELECT depth in one token pass. */
function hasRealSelectStar(sql: string, original = sql, conservativeSource = sql): boolean {
  const conservative = AMBIGUOUS_QUOTING.test(original)
    ? { source: conservativeSource, selects: [...conservativeSource.matchAll(CONSERVATIVE_SELECT)].map((match) => ({ offset: match.index, allowsStar: selectAllowsStar(conservativeSource, match.index) })) }
    : undefined;
  const strictSuffix = /[\x60[\]\\?]/u.test(original);
  const projections = new Map<number, Projection>();
  const existsScopes = new Set<number>();
  let depth = 0;
  let previous = "";
  let prior = "";
  for (const match of sql.matchAll(SQL_TOKEN)) {
    const raw = match[0];
    const token = ASCII_WORD.test(raw) ? raw.toUpperCase() : raw;
    if (token === ")") {
      projections.delete(depth);
      existsScopes.delete(depth);
      depth = Math.max(0, depth - 1);
    }
    const projection = projections.get(depth);
    if (isKeyword(token, previous, "SELECT")) {
      projections.set(depth, { exists: existsScopes.size > 0, strictSuffix, conservative, prefix: [], star: false });
    } else if (isKeyword(token, previous, "FROM")) {
      if (projection?.star === true) return true;
      projections.delete(depth);
    } else if (token === ";") {
      projections.clear();
      existsScopes.clear();
    } else if (projection !== undefined) {
      observeProjection(sql, match, previous, projection);
    }
    if (token === "(") {
      depth += 1;
      if (isKeyword(previous, prior, "EXISTS")) existsScopes.add(depth);
    }
    prior = previous;
    previous = token;
  }
  return false;
}

function selectAllowsStar(source: string, offset: number): boolean {
  const opening = skipWhitespace(source, offset - 1, -1);
  if (source[opening] !== "(") return true;
  const wordEnd = skipWhitespace(source, opening - 1, -1);
  const wordStart = wordEnd - EXISTS_KEYWORD_LENGTH + 1;
  return wordStart < 0 || source.slice(wordStart, wordEnd + 1).toUpperCase() !== "EXISTS" ||
    (wordStart !== 0 && ASCII_IDENTIFIER_CHARACTER.test(source[wordStart - 1] ?? ""));
}

function isKeyword(token: string, previous: string, keyword: string): boolean {
  return token === keyword && previous !== ".";
}

function observeProjection(sql: string, match: RegExpExecArray, previous: string, projection: Projection): void {
  if (isProjectionStar(sql, match, previous, projection)) {
    if (projection.conservative === undefined || conservativeProjectionStar(projection.conservative, match.index)) {
      projection.star = true;
    }
  } else if (projection.prefix.length < 2) {
    const raw = match[0];
    projection.prefix.push(ASCII_WORD.test(raw) ? raw.toUpperCase() : raw);
  }
}


/** Preserve established match boundaries when bracket/backtick syntax has multiple dialect meanings. */
function conservativeProjectionStar(query: ConservativeSql, offset: number): boolean {
  const { source, selects } = query;
  let low = 0;
  let high = selects.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    const start = selects[middle];
    if (start !== undefined && start.offset < offset) low = middle + 1;
    else high = middle;
  }
  const owning = selects[low - 1];
  if (owning?.allowsStar !== true) return false;
  if (source[offset - 1] === "." && ASCII_IDENTIFIER_CHARACTER.test(source[offset - 2] ?? "")) return true;
  const before = skipWhitespace(source, offset - 1, -1);
  const after = skipWhitespace(source, offset + 1, 1);
  const afterChar = source[after] ?? "";
  CONSERVATIVE_FROM.lastIndex = after;
  return (afterChar === "" || afterChar === "," || afterChar === ")" || CONSERVATIVE_FROM.test(source)) &&
    !(source[before] === "(" && afterChar === ")");
}

function skipWhitespace(source: string, offset: number, direction: -1 | 1): number {
  let cursor = offset;
  while (cursor >= 0 && cursor < source.length && SQL_WHITESPACE.test(source[cursor] ?? "")) cursor += direction;
  return cursor;
}

function isProjectionStar(sql: string, match: RegExpExecArray, previous: string, projection: Projection): boolean {
  if (match[0] !== "*" || projection.exists) return false;
  const { prefix } = projection;
  if (previous === ".") return true;
  if (!projection.strictSuffix && (prefix.length === 0 || previous === ",")) return true;
  if (!endsProjection(sql, match.index + 1)) return false;
  return previous === "SELECT" || previous === "," || SELECT_PREFIX_WORDS.has(previous) ||
    (previous === ")" && ((prefix[0] === "DISTINCT" && prefix[1] === "ON") || prefix[0] === "TOP"));
}

function endsProjection(sql: string, offset: number): boolean {
  PROJECTION_END.lastIndex = offset;
  return PROJECTION_END.test(sql);
}


export default createRule<Options, MessageIds>({
  name: "no-select-star",
  documentation: NO_SELECT_STAR_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: {
      description:
        "Prefer explicit column projections over SELECT * in embedded SQL.",
    },
    schema: [],
    messages: {
      noSelectStar:
        "`SELECT *` over-fetches and leaves the row shape implicit — a new or reordered column silently changes what this query returns. List the columns explicitly.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context)) {
      return {};
    }
    return createSqlListener((sql: string, node: TSESTree.Node, original: string): void => {
      if (!hasQueryShape(sql)) return;
      const conservativeSource = AMBIGUOUS_QUOTING.test(original) ? stripSqlNoise(original) : sql;
      if (!hasRealSelectStar(sql, original, conservativeSource)) return;
      context.report({ node, messageId: "noSelectStar" });
    }, { preserveQuotedTokens: true });
  },
});
