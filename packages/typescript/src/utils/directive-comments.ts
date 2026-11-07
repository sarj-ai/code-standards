/** @fileoverview directive-comments — the directive comments of a file and the areas their disable and enable directives cover. */
/*!
 * Adapted from @eslint-community/eslint-plugin-eslint-comments 4.8.1,
 * lib/internal/utils.js, get-all-directive-comments.js and disabled-area.js.
 * MIT License
 * Copyright (c) 2016 Toru Nagashima
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

// Differences from the upstream plugin:
// - Disable and enable directives come from Oxlint's `getDisableDirectives`,
//   so both `eslint-*` and `oxlint-*` spellings count, in line and block
//   comments, exactly as Oxlint applies them. `/* eslint ... */`,
//   `/* eslint-env */`, `/* exported */` and `/* global(s) */` are still parsed
//   from block comments.
// - Reports land on the directive keyword or the rule name inside the comment
//   instead of one column before the comment. Oxlint rejects that column on
//   line 1, and a report there would fall inside the area the directive
//   itself disables.

import type { Comment, SourceCode } from "@oxlint/plugins";

/** A directive comment: `kind` as written (`oxlint-disable-line`), its value and its `--` description ("" when absent). */
export interface DirectiveComment {
  readonly kind: string;
  readonly value: string;
  readonly description: string;
  readonly comment: Comment;
}

/** A position compared like ESLint locations; column -1 sorts before a line's first character. */
interface Position {
  readonly line: number;
  readonly column: number;
}

/** The rules (`ruleId === null` for every rule) one disable directive turns off from `start` to `end`. */
export interface DisabledArea {
  readonly comment: Comment;
  readonly ruleId: string | null;
  readonly kind: "block" | "line";
  readonly start: Position;
  readonly end: Position | null;
}

type OpenArea = { -readonly [Field in keyof DisabledArea]: DisabledArea[Field] };

export interface DirectiveAreas {
  readonly areas: readonly DisabledArea[];
  readonly duplicateDisables: readonly { readonly comment: Comment; readonly ruleId: string | null }[];
  readonly unusedEnables: readonly { readonly comment: Comment; readonly ruleId: string | null }[];
  /** For each enable directive, how many disable directives it closed. */
  readonly closedDisables: ReadonlyMap<Comment, number>;
}

// Directives other than disable/enable, which only block comments carry.
const OTHER_DIRECTIVE_RE = /^(eslint(?:-env)?|exported|globals?)(?:\s|$)/u;
const DESCRIPTION_SEPARATOR_RE = /\s-{2,}\s/u;
const KEYWORD_RE = /^(\s*)(\S+)/u;
const PREFIX_RE = /^\s*(eslint|oxlint)-/u;
const RULE_DELIMITER_RE = /[\s,]+/u;
const RULE_WORD_RE = /[^\s,]+/gu;

// Several rules read these per file. Oxlint reuses one SourceCode for every file, so cache per AST.
const COMMENTS = new WeakMap<object, readonly DirectiveComment[]>();
const AREAS = new WeakMap<object, DirectiveAreas>();

/** Every directive comment in source order. */
export function directiveComments(sourceCode: SourceCode): readonly DirectiveComment[] {
  let comments = COMMENTS.get(sourceCode.ast);
  if (comments === undefined) {
    comments = collectDirectiveComments(sourceCode);
    COMMENTS.set(sourceCode.ast, comments);
  }
  return comments;
}

function collectDirectiveComments(sourceCode: SourceCode): DirectiveComment[] {
  const { directives } = sourceCode.getDisableDirectives();
  const disableStarts = new Set(directives.map((directive) => directive.node.range[0]));
  const others = sourceCode.getAllComments().flatMap((comment): DirectiveComment[] => {
    if (comment.type !== "Block" || disableStarts.has(comment.range[0])) return [];
    const [text = "", description = ""] = comment.value.split(DESCRIPTION_SEPARATOR_RE).map((part) => part.trim());
    const kind = OTHER_DIRECTIVE_RE.exec(text)?.[1];
    return kind === undefined ? [] : [{ kind, value: text.slice(kind.length).trim(), description, comment }];
  });
  return [
    ...directives.map((directive) => ({
      kind: `${PREFIX_RE.exec(directive.node.value)?.[1] ?? "eslint"}-${directive.type}`,
      value: directive.value,
      description: directive.justification,
      comment: directive.node,
    })),
    ...others,
  ].sort((left, right) => left.comment.range[0] - right.comment.range[0]);
}

/** The `eslint-*` spelling of a directive kind, so `oxlint-*` directives follow the options written for `eslint-*`. */
export function eslintSpelling(kind: string): string {
  return kind.replace(/^oxlint-/u, "eslint-");
}

/** The areas the file's disable directives cover, with their duplicates and unused enables. */
export function directiveAreas(sourceCode: SourceCode): DirectiveAreas {
  let areas = AREAS.get(sourceCode.ast);
  if (areas === undefined) {
    areas = collectDirectiveAreas(sourceCode);
    AREAS.set(sourceCode.ast, areas);
  }
  return areas;
}

function collectDirectiveAreas(sourceCode: SourceCode): DirectiveAreas {
  const areas: OpenArea[] = [];
  const duplicateDisables: { comment: Comment; ruleId: string | null }[] = [];
  const unusedEnables: { comment: Comment; ruleId: string | null }[] = [];
  const closedDisables = new Map<Comment, number>();

  const disable = (comment: Comment, start: Position, ruleIds: readonly string[] | null, kind: DisabledArea["kind"]): void => {
    for (const ruleId of ruleIds ?? [null]) {
      if (areaAt(ruleId, start) !== undefined) duplicateDisables.push({ comment, ruleId });
      areas.push({ comment, ruleId, kind, start, end: null });
    }
  };

  const enable = (comment: Comment, end: Position, ruleIds: readonly string[] | null, kind: DisabledArea["kind"]): void => {
    const closed = new Set<Comment>();
    for (const ruleId of ruleIds ?? [null]) {
      let used = false;
      for (const area of areas) {
        if (area.end !== null || area.kind !== kind || (ruleId !== null && area.ruleId !== ruleId)) continue;
        closed.add(area.comment);
        area.end = end;
        used = true;
      }
      if (!used) unusedEnables.push({ comment, ruleId });
    }
    closedDisables.set(comment, closed.size);
  };

  const areaAt = (ruleId: string | null, location: Position): DisabledArea | undefined =>
    areas.findLast((area) =>
      (area.ruleId === null || area.ruleId === ruleId) &&
      lte(area.start, location) &&
      (area.end === null || lte(location, area.end)));

  for (const directive of sourceCode.getDisableDirectives().directives) {
    const ruleIds = directive.value === "" ? null : directive.value.split(RULE_DELIMITER_RE);
    const comment = directive.node;
    const { line, column } = comment.loc.start;
    switch (directive.type) {
      case "disable":
        disable(comment, { line, column }, ruleIds, "block");
        break;
      case "enable":
        enable(comment, { line, column }, ruleIds, "block");
        break;
      case "disable-line":
        disable(comment, { line, column: 0 }, ruleIds, "line");
        enable(comment, { line: line + 1, column: -1 }, ruleIds, "line");
        break;
      case "disable-next-line":
        disable(comment, { line: line + 1, column: 0 }, ruleIds, "line");
        enable(comment, { line: line + 2, column: -1 }, ruleIds, "line");
        break;
    }
  }
  return { areas, duplicateDisables, unusedEnables, closedDisables };
}

export function lte(left: Position, right: Position): boolean {
  return left.line < right.line || (left.line === right.line && left.column <= right.column);
}

/** The directive keyword of a directive comment, e.g. `eslint-disable` in `/* eslint-disable no-console *\/`. */
export function directiveLocation(sourceCode: SourceCode, comment: Comment): Comment["loc"] {
  const [, leading = "", keyword = ""] = KEYWORD_RE.exec(comment.value) ?? [];
  // `//` and `/*` both open with two characters before the comment value.
  const start = comment.range[0] + 2 + leading.length;
  return { start: sourceCode.getLocFromIndex(start), end: sourceCode.getLocFromIndex(start + keyword.length) };
}

/** Where `ruleId` is named in a directive comment, or the directive keyword when it names every rule. */
export function ruleIdLocation(sourceCode: SourceCode, comment: Comment, ruleId: string | null): Comment["loc"] {
  // The first comma- or whitespace-delimited word equal to the rule ID.
  const match = ruleId === null ? undefined : comment.value.matchAll(RULE_WORD_RE).find(([word]) => word === ruleId);
  if (ruleId === null || match === undefined) return directiveLocation(sourceCode, comment);
  const start = comment.range[0] + 2 + match.index;
  return { start: sourceCode.getLocFromIndex(start), end: sourceCode.getLocFromIndex(start + ruleId.length) };
}
