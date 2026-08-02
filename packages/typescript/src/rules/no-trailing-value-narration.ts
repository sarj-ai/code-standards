/**
 * @fileoverview no-trailing-value-narration — a trailing comment restating the literal beside it drifts the moment someone edits the arithmetic.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-trailing-value-narration.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
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

export default createRule<Options, MessageIds>({
  name: "no-trailing-value-narration",
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
