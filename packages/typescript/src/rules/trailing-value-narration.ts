/**
 * @fileoverview Flag a trailing comment that spells out a literal already on the
 * line — the TypeScript twin of Python's SARJ051.
 *
 *     staleTime: 5 * 60 * 1000, // 5 minutes
 *
 * The comment adds one thing — the unit — and the line already carries every
 * number in it. Put the unit in the *name* (`STALE_TIME_MS`, a `Duration`
 * helper) and the fact travels with the value: it survives a copy-paste, it is
 * visible at every call site, and it cannot drift when someone edits the
 * arithmetic and forgets the comment. That drift is the whole risk — a wrong
 * unit comment is worse than none.
 *
 * **The test is deliberately narrow.** Every one of these must hold: the code
 * before the comment contains a numeric literal; the comment contains at least
 * one number and EVERY number it contains appears verbatim in that code; and
 * every non-numeric word is either a unit word or already an identifier on the
 * line. So `// 5 minutes` over `5 * 60 * 1000` fires, while `// ~3.5 days` over
 * `300000` — a conversion the reader cannot do in their head — does not, and
 * neither does `// doubles per attempt, capped by the gateway`. A comment
 * carrying a ticket or URL is exempt (protected-class signal S1).
 *
 * **Measured.** 18 hits across the nine-repo corpus, 18 of 18 true positives.
 * They cluster hard: one first-party analytics-hooks module
 * alone holds 12 `staleTime` lines, its sibling `lib/query-client.ts` two more,
 * and a first-party Worker config module carries
 * `export const COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 90; // 90 days`.
 */

import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { codeTokens, hasExternalReference, stem } from "./_comments.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "narratesValue";
type Options = readonly [];

// A number that is not part of an identifier or a dotted member path.
const NUMBER_RE = /(?<![\w.])(\d+(?:\.\d+)?)(?![\w.])/g;
const WORD_RE = /[A-Za-z]+(?:'[a-z]+)?|\d+(?:\.\d+)?/g;

// Words that name the unit rather than the quantity — the one thing the code
// does not say, and the reason the fix is a *name*, not a deletion.
const UNIT_WORDS: ReadonlySet<string> = new Set([
  "bytes", "characters", "chars", "day", "days", "gb", "hour", "hours", "hr",
  "hrs", "hz", "items", "k", "kb", "khz", "m", "mb", "milliseconds", "min",
  "mins", "minute", "minutes", "ms", "pct", "percent", "px", "retries", "rows",
  "s", "sec", "second", "seconds", "secs", "times", "tokens",
]);

const STOPWORDS: ReadonlySet<string> = new Set([
  "a", "an", "and", "are", "as", "at", "be", "by", "for", "in", "is", "it",
  "of", "on", "or", "that", "the", "this", "we", "with",
]);

const DIRECTIVE_RE =
  /^\s*(?:eslint\b|eslint-|sarj-noqa\b|@ts-|prettier|biome-|c8\b|v8\b|istanbul\b|todo\b|fixme\b|hack\b|xxx\b)/i;

function numbersIn(text: string): Set<string> {
  return new Set(text.match(NUMBER_RE) ?? []);
}

function narratesValue(body: string, code: string): boolean {
  if (body.length === 0 || DIRECTIVE_RE.test(body) || hasExternalReference(body)) return false;
  const codeNumbers = numbersIn(code);
  if (codeNumbers.size === 0) return false;
  const words = (body.match(WORD_RE) ?? []).map((word) => word.toLowerCase());
  if (words.length === 0) return false;
  const commentNumbers = numbersIn(body);
  if (commentNumbers.size === 0) return false;
  for (const number of commentNumbers) {
    if (!codeNumbers.has(number)) return false;
  }
  const identifiers = codeTokens(code);
  const stems = new Set<string>();
  for (const token of identifiers) stems.add(stem(token));
  return words.every(
    (word) =>
      STOPWORDS.has(word) ||
      UNIT_WORDS.has(word) ||
      commentNumbers.has(word) ||
      identifiers.has(word) ||
      stems.has(stem(word)),
  );
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "trailing-value-narration",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag a trailing comment whose every word and number is already on the line it annotates.",
    },
    schema: [],
    messages: {
      narratesValue:
        "Trailing comment restates the literal on this line — put the unit in the name (STALE_TIME_MS) so it cannot drift.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const sourceCode = context.sourceCode;

    function isTrailing(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      return before !== null && before.loc.end.line === comment.loc.start.line;
    }

    return {
      Program(): void {
        for (const comment of sourceCode.getAllComments()) {
          if (!isTrailing(comment)) continue;
          const line = sourceCode.lines[comment.loc.start.line - 1] ?? "";
          const code = line.slice(0, comment.loc.start.column);
          const body = comment.value.replace(/^\*+/, "").replace(/\*+$/, "").trim();
          if (narratesValue(body, code)) {
            context.report({ node: comment, messageId: "narratesValue" });
          }
        }
      },
    };
  },
});
