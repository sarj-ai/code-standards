/**
 * @fileoverview _comment-wall — the shared judgement behind the comment-VOLUME rules: a run of member comments that mostly re-spell their members is a wall.
 *
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { isProtected, splitIdentifier, stem } from "./_comments.js";

/** Every threshold the wall rules apply; each is documented at `WALL_DEFAULTS`. */
export interface WallOptions {
  readonly minCommentedMembers: number;
  readonly minCommentedRatio: number;
  readonly minRestatedRatio: number;
  readonly maxNovelWords: number;
}

export const WALL_DEFAULTS: WallOptions = {
  // Below three rows "a wall" is not a fair description of what the reader sees.
  minCommentedMembers: 3,
  // A minority of commented members is a GROUP LABEL, not a wall.
  minCommentedRatio: 0.6,
  // Room for one substantive row in four; a declaration where a quarter of the
  // comments say something real is one someone was documenting, not decorating.
  minRestatedRatio: 0.75,
  maxNovelWords: 1,
};

/** The `meta.schema` entry both wall rules expose, so the knobs cannot drift. */
export const WALL_SCHEMA = {
  type: "object",
  additionalProperties: false,
  properties: {
    minCommentedMembers: {
      type: "integer",
      minimum: 2,
      description: "Fewest commented members that can count as a wall.",
    },
    minCommentedRatio: {
      type: "number",
      minimum: 0,
      maximum: 1,
      description:
        "Least share of the members that must be commented; below it the comments are group labels.",
    },
    minRestatedRatio: {
      type: "number",
      minimum: 0,
      maximum: 1,
      description: "Least share of the member comments that must be restatements.",
    },
    maxNovelWords: {
      type: "integer",
      minimum: 0,
      description:
        "Most content words a comment may add beyond its member's own source and still count as a restatement.",
    },
  },
} as const;

const VALUE_TAG_RE =
  /@(?:deprecated|see|example|throws|remarks|since|default|defaultvalue|link|internal|alpha|beta|experimental|template|typeparam|inheritdoc|todo|fixme|override)\b/i;

const DEFAULT_RE = /^\s*@?default\b|\bdefaults? (?:to|:)/i;

const DIGIT_RE = /\d/;
const UNIT_WORD_RE =
  /\b(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|bytes?|kb|mb|gb|percent|pixels?|px|utc|epoch)\b/i;

// A quoted example value or an `e.g.` enumerates what the type only bounds.
const EXAMPLE_RE = /["'`]|\be\.g\.|\bi\.e\./;

// Every word of the body belongs to a JSDoc tag, so the block is an instruction
// to a documentation generator rather than a sentence about the member.
const TAG_TOKEN_RE = /@\w+/g;

// A rule of dashes is a banner; `no-comment-cruft` owns that shape.
const BANNER_RE = /[=\-─-╿*#~_.]{3,}/;

// Prose the tokenizer cannot read, so "adds no new word" is unmeasurable.
const NON_ASCII_LETTER_RE = /[^\p{ASCII}\p{N}\p{P}\p{Z}]/u;

export const WALL_STOPWORDS: ReadonlySet<string> = new Set(
  `the a an of to for in on with and or as at by is are was be been being
   this that it its if whether when where which what will would can could should
   must may into from over about not no does do done has have had used use uses
   using given provided specified current new existing all any each per via
   instance object value values data item
   items element callback handler prop props param arg return
   returns returning result optional required true false null undefined
   string number boolean array list promise set map record type name`.split(/\s+/),
);

const WORD_RE = /[A-Za-z][A-Za-z0-9]*/g;

export const BARE_LABEL_RE = /^[A-Za-z][A-Za-z0-9]*$/;

/** The identifier `body` spells, folded so `links` and `Links` are one word. */
export function labelStems(body: string): string {
  return splitIdentifier(body).map(stem).join(" ");
}

/** Strip the `*` decoration off a block comment so JSDoc and `//` read alike. */
export function commentBody(comment: TSESTree.Comment): string {
  return comment.value
    .replace(/^\*+/, "")
    .replace(/^[ \t]*\*[ \t]?/gm, "")
    .trim();
}

export function carriesValue(body: string): boolean {
  return (
    isProtected(body) ||
    VALUE_TAG_RE.test(body) ||
    DEFAULT_RE.test(body) ||
    DIGIT_RE.test(body) ||
    UNIT_WORD_RE.test(body) ||
    EXAMPLE_RE.test(body) ||
    BANNER_RE.test(body) ||
    NON_ASCII_LETTER_RE.test(body)
  );
}

export function isLabel(body: string): boolean {
  let content = 0;
  for (const word of body.match(WORD_RE) ?? []) {
    if (word.length >= 2 && !WALL_STOPWORDS.has(word.toLowerCase())) content += 1;
  }
  return content <= 1;
}

/** True when `body` carries no prose at all beyond its JSDoc tags. */
export function isTagsOnly(body: string): boolean {
  return body.length > 0 && body.replace(TAG_TOKEN_RE, "").trim().length === 0;
}

/** Every identifier part of a slice of source, plus its stem. */
export function knownTokens(source: string): ReadonlySet<string> {
  const tokens = new Set<string>();
  for (const identifier of source.match(/[A-Za-z_$][\w$]*/g) ?? []) {
    for (const part of splitIdentifier(identifier)) {
      tokens.add(part);
      tokens.add(stem(part));
    }
  }
  return tokens;
}

/** Content words of `body` that do not already appear in `known`. */
export function novelWords(body: string, known: ReadonlySet<string>): number {
  let novel = 0;
  for (const word of body.match(WORD_RE) ?? []) {
    const lower = word.toLowerCase();
    if (lower.length < 2 || WALL_STOPWORDS.has(lower)) continue;
    if (!known.has(lower) && !known.has(stem(lower))) novel += 1;
  }
  return novel;
}

/**
 * True when a run of members carrying `commented` comments, `restated` of them
 * restatements, is a wall under `options`.
 */
export function isWall(
  members: number,
  commented: number,
  restated: number,
  options: WallOptions,
): boolean {
  return (
    commented >= options.minCommentedMembers &&
    commented / members >= options.minCommentedRatio &&
    restated / commented >= options.minRestatedRatio
  );
}

const OPAQUE_VALUE_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([
  AST_NODE_TYPES.FunctionExpression,
  AST_NODE_TYPES.ArrowFunctionExpression,
  AST_NODE_TYPES.ObjectExpression,
  AST_NODE_TYPES.ArrayExpression,
]);

export interface DeclarationRange {
  readonly end: number;
  readonly start: number;
}

export function declarationRange(member: TSESTree.Node): DeclarationRange {
  const body = bodyOf(member);
  return {
    end: body?.range[0] ?? member.range[1],
    start: member.range[0],
  };
}

function bodyOf(member: TSESTree.Node): TSESTree.Node | undefined {
  if (
    member.type === AST_NODE_TYPES.MethodDefinition ||
    member.type === AST_NODE_TYPES.TSAbstractMethodDefinition
  ) {
    return member.value.body ?? undefined;
  }
  if (member.type === AST_NODE_TYPES.Property || member.type === AST_NODE_TYPES.PropertyDefinition) {
    const value = member.value;
    if (value !== null && OPAQUE_VALUE_TYPES.has(value.type)) return value;
  }
  return undefined;
}
