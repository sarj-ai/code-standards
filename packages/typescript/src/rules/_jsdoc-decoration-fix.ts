/**
 * @fileoverview _jsdoc-decoration-fix — remove interior JSDoc decoration without changing prose.
 */

/** Exact interior JSDoc decoration edits; preserve every prose byte and line. */

import { type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { ownLineCommentRemovalRange } from "./_comment-edits.js";

const PROTECTED_CONTEXT_RE = /@|copyright|licen[cs]e|spdx|permission is hereby granted|all rights reserved|credential|password|secret|token|\b(?:eslint|prettier|biome|istanbul|noqa|sarj-noqa|c8|v8|coding|encoding|bearer|authorization|authentication|examples?|samples?|outputs?|stdout|stderr|expected|literal|verbatim|transcripts?|golden|fixtures?|snippets?|grammar|logs?|console|terminals?|ascii|snapshots?|prompts?|keys?|certificates?|signatures?|checksums?|hashes?|base64|diagrams?|tables?|matrices|diffs?|patches)\b|https?:\/\//iu;
const STRUCTURAL_CONTEXT_RE = /[`~#*_[\]{}=<>|\\/"']|(?:^|\n)\s*(?:[-+]\s|\d+[.)]\s|[-=]{3,})/u;
const DECORATION_LINE_RE = /^[\t ]*\*[\t ]*(\+{4,})[\t ]*(?:\r?\n)?$/u;

interface DecorationEdit {
  readonly range: readonly [number, number];
}

/** Offer only actual native progress after removing plus-only decoration. */
export function jsdocDecorationFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  comment: TSESTree.Comment,
  accepts: (text: string) => boolean,
): ((fixer: TSESLint.RuleFixer) => TSESLint.RuleFix[]) | null {
  if (comment.type !== "Block" || !comment.value.startsWith("*") ||
    ownLineCommentRemovalRange(sourceCode.text, comment) === null) return null;
  const raw = sourceCode.getText(comment);
  const text = body(raw);
  const prose = text.split("\n").filter((line) => !/^\s*\+{4,}\s*$/u.test(line)).join("\n");
  if (PROTECTED_CONTEXT_RE.test(text) || STRUCTURAL_CONTEXT_RE.test(prose) ||
    prose.includes("+") || hasIndentedExample(raw)) return null;
  const edits: DecorationEdit[] = [];
  let offset = comment.range[0];
  for (const line of raw.split(/(?<=\n)/u)) {
    const plus = DECORATION_LINE_RE.exec(line)?.[1];
    if (plus !== undefined) {
      const start = offset + line.indexOf(plus);
      edits.push({ range: [start, start + plus.length] });
    }
    offset += line.length;
  }
  if (edits.length === 0) return null;
  let fixed = raw;
  for (const edit of edits.toReversed()) {
    fixed = fixed.slice(0, edit.range[0] - comment.range[0]) + fixed.slice(edit.range[1] - comment.range[0]);
  }
  if (!accepts(body(fixed))) return null;
  return (fixer) => edits.map((edit) => fixer.replaceTextRange(edit.range, ""));
}

function body(raw: string): string {
  return raw.slice(2, -2).replace(/^\*/u, "").split("\n")
    .map((line) => line.replace(/^\s*\*?\s?/u, "")).join("\n").trim();
}

function hasIndentedExample(raw: string): boolean {
  return raw.slice(2, -2).replace(/^\*/u, "").split("\n").some((line) => {
    const content = line.replace(/^[\t ]*\*(?: ?)/u, "");
    return content.trim().length > 0 && /^(?: {4}|\t)/u.test(content);
  });
}
