/**
 * @fileoverview An object type whose member comments mostly re-spell the
 * members' own names and types — the VOLUME arm of the comment family, judged
 * once per TYPE rather than once per comment.
 *
 *     interface SapCredentials {
 *       // Database host.
 *       host?: string;
 *       // Database host port.
 *       port?: number;
 *       // Database username.
 *       username?: string;
 *     }
 *
 * `jsdoc-restates-signature` needs every content word covered, so it deletes
 * the first row and cannot touch the second. That is the right verdict for one
 * line and the wrong one for ten, so the unit of judgement here is the type.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-type-member-comment-wall.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-type-member-comment-wall.md
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isProtected, splitIdentifier, stem } from "./_comments.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "commentWall";

/** Every threshold this rule applies; each is documented at `DEFAULTS`. */
export interface RuleOptions {
  readonly minCommentedMembers: number;
  readonly minCommentedRatio: number;
  readonly minRestatedRatio: number;
  readonly maxNovelWords: number;
}

type Options = readonly [Partial<RuleOptions>?];

const DEFAULTS: RuleOptions = {
  // Below three rows "a wall" is not a fair description of what the reader sees.
  minCommentedMembers: 3,
  // A minority of commented members is a GROUP LABEL, not a wall.
  minCommentedRatio: 0.6,
  // Room for one substantive row in four; a type where a quarter of the comments
  // say something real is a type someone was documenting, not decorating.
  minRestatedRatio: 0.75,
  // One word beyond the member's own text. Zero is `jsdoc-restates-signature`'s
  // test and is already covered there; two admits definitions ("Partial match"
  // beside "Exact match"), which the evidence file counts.
  maxNovelWords: 1,
};

// Tags that carry what the signature cannot — kept in step with
// `jsdoc-restates-signature`'s VALUE_TAGS.
const VALUE_TAG_RE =
  /@(?:deprecated|see|example|throws|remarks|since|default|defaultvalue|link|internal|alpha|beta|experimental|template|typeparam|inheritdoc|todo|fixme|override)\b/i;

// A documented default. The default of an optional member is precisely the fact
// its type cannot hold.
const DEFAULT_RE = /^\s*@?default\b|\bdefaults? (?:to|:)/i;

// A digit is a bound, a base, an index origin, a status code or a version — all
// facts about the world rather than about the name. A unit word is the same fact
// spelled without one.
const DIGIT_RE = /\d/;
const UNIT_WORD_RE =
  /\b(?:ms|milliseconds?|seconds?|minutes?|hours?|days?|weeks?|months?|years?|bytes?|kb|mb|gb|percent|pixels?|px|utc|epoch)\b/i;

// A quoted example value or an `e.g.` enumerates what the type only bounds.
const EXAMPLE_RE = /["'`]|\be\.g\.|\bi\.e\./;

// A rule of dashes is a banner; `no-comment-cruft` owns that shape.
const BANNER_RE = /[=\-─-╿*#~_.]{3,}/;

// Prose the tokenizer cannot read, so "adds no new word" is unmeasurable.
const NON_ASCII_LETTER_RE = /[^\p{ASCII}\p{N}\p{P}\p{Z}]/u;

/**
 * Filler that says nothing about *which* member is being described. Wider than
 * `_comments.STOPWORDS` for the same reason `jsdoc-restates-signature`'s list
 * is: member documentation conventionally repeats the vocabulary of the type
 * system itself ("the optional callback value") without that being a claim.
 *
 * Deliberately absent: `class`, `method`, `function`, `component`, `hook`,
 * `parameter`, `argument`. In a reflection or decorator type those words are
 * the whole claim — `Function` cannot say "class" and `number` cannot say
 * "parameter". The tag words `param` and `arg` stay: block punctuation, not
 * prose.
 */
const STOPWORDS: ReadonlySet<string> = new Set(
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

// A label is one bare identifier word: `// links`, `// clientMiddleware`. Two
// words of prose is already a sentence about the member below it.
const BARE_LABEL_RE = /^[A-Za-z][A-Za-z0-9]*$/;

/** The identifier `body` spells, folded so `links` and `Links` are one word. */
function labelStems(body: string): string {
  return splitIdentifier(body).map(stem).join(" ");
}

/** A member the rule can judge: a named property or method signature. */
type NamedMember = TSESTree.TSPropertySignature | TSESTree.TSMethodSignature;

function isNamedMember(node: TSESTree.TypeElement): node is NamedMember {
  return (
    (node.type === AST_NODE_TYPES.TSPropertySignature ||
      node.type === AST_NODE_TYPES.TSMethodSignature) &&
    !node.computed
  );
}

/** Strip the `*` decoration off a block comment so JSDoc and `//` read alike. */
function commentBody(comment: TSESTree.Comment): string {
  return comment.value
    .replace(/^\*+/, "")
    .replace(/^[ \t]*\*[ \t]?/gm, "")
    .trim();
}

/**
 * True when a member comment carries something a name and a type cannot — the
 * exemption floor for this rule. Counted as a comment, never as a restatement.
 */
function carriesValue(body: string): boolean {
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

/** Every identifier part of a slice of source, plus its stem. */
function knownTokens(source: string): ReadonlySet<string> {
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
function novelWords(body: string, known: ReadonlySet<string>): number {
  let novel = 0;
  for (const word of body.match(WORD_RE) ?? []) {
    const lower = word.toLowerCase();
    if (lower.length < 2 || STOPWORDS.has(lower)) continue;
    if (!known.has(lower) && !known.has(stem(lower))) novel += 1;
  }
  return novel;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-type-member-comment-wall",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag an object type whose member comments mostly re-spell the members' own names and types.",
    },
    schema: [
      {
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
              "Least share of the type's members that must be commented; below it the comments are group labels.",
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
      },
    ],
    messages: {
      commentWall:
        "{{restated}} of this type's {{commented}} member comments only re-spell the member's own name and type — delete them, and keep the rows that say what the name cannot.",
    },
  },
  defaultOptions: [DEFAULTS],
  create(context, [provided]) {
    const options: RuleOptions = { ...DEFAULTS, ...provided };
    const sourceCode = context.sourceCode;
    // Generated or vendored, a test fixture, or a demo story: three kinds of
    // file whose member comments are output rather than commentary.
    if (
      isGeneratedFile(context.filename, sourceCode.text) ||
      isTestFile(context.filename) ||
      isStoryFile(context.filename)
    ) {
      return {};
    }

    // One pass over the file's comments, indexed by the line they end on (a
    // leading comment) and the line they start on (a trailing one).
    const endingOn = new Map<number, TSESTree.Comment>();
    const startingOn = new Map<number, TSESTree.Comment>();
    for (const comment of sourceCode.getAllComments()) {
      endingOn.set(comment.loc.end.line, comment);
      if (!startingOn.has(comment.loc.start.line)) startingOn.set(comment.loc.start.line, comment);
    }

    /**
     * The comment documenting `member`: the block or line comment on the row
     * above it, or the one trailing its last row.
     *
     * A leading comment counts only when the MEMBER starts its own line, and
     * only when the comment is alone on ITS line; a trailing comment counts
     * only when it sits after the member it is read against. All three keep a
     * one-line type literal under a doc block from reading as three members
     * documented three times with the same words.
     */
    function documentingComment(member: NamedMember): TSESTree.Comment | undefined {
      const beforeMember = sourceCode.getTokenBefore(member, { includeComments: false });
      const ownsItsLine =
        beforeMember === null || beforeMember.loc.end.line < member.loc.start.line;
      const lead = ownsItsLine ? endingOn.get(member.loc.start.line - 1) : undefined;
      if (lead !== undefined) {
        const before = sourceCode.getTokenBefore(lead, { includeComments: false });
        if (before === null || before.loc.end.line < lead.loc.start.line) return lead;
      }
      const trail = startingOn.get(member.loc.end.line);
      return trail !== undefined && trail.range[0] > member.range[0] ? trail : undefined;
    }

    /**
     * True when a comment heads a REGION of the type instead of describing the
     * member under it — the exemption this rule documents and, before this
     * check, leaked on.
     *
     * Three conditions. The body is ONE bare identifier word; it names
     * something OTHER than the member below it (the decisive one — `// links`
     * over `LinkDescriptors` heads a group, `// links` over `links` restates a
     * name); and it shows region evidence, heading a run of members of which
     * only the first is commented, or set off by a blank line.
     */
    function isGroupLabel(
      comment: TSESTree.Comment,
      member: NamedMember,
      headsRun: boolean,
    ): boolean {
      if (comment.loc.end.line >= member.loc.start.line) return false;
      const body = commentBody(comment);
      if (!BARE_LABEL_RE.test(body)) return false;
      if (labelStems(body) === labelStems(sourceCode.getText(member.key))) return false;
      const lineAbove = sourceCode.lines[comment.loc.start.line - 2];
      return headsRun || (lineAbove !== undefined && lineAbove.trim().length === 0);
    }

    function check(node: TSESTree.TSInterfaceBody | TSESTree.TSTypeLiteral): void {
      const members = node.type === AST_NODE_TYPES.TSInterfaceBody ? node.body : node.members;
      const named = members.filter(isNamedMember);
      if (named.length === 0) return;

      const documented = named.map((member) => ({ member, comment: documentingComment(member) }));
      let commented = 0;
      let restated = 0;
      // A comment documents at most one member, so a shared block cannot be
      // counted once per member that happens to sit next to it.
      const claimed = new Set<TSESTree.Comment>();
      for (const [index, { member, comment }] of documented.entries()) {
        if (comment === undefined || claimed.has(comment)) continue;
        const next = documented[index + 1];
        if (isGroupLabel(comment, member, next !== undefined && next.comment === undefined)) {
          continue;
        }
        claimed.add(comment);
        commented += 1;
        const body = commentBody(comment);
        if (body.length === 0 || carriesValue(body)) continue;
        if (novelWords(body, knownTokens(sourceCode.getText(member))) <= options.maxNovelWords) {
          restated += 1;
        }
      }

      if (
        commented < options.minCommentedMembers ||
        commented / named.length < options.minCommentedRatio ||
        restated / commented < options.minRestatedRatio
      ) {
        return;
      }
      context.report({
        node,
        loc: {
          start: node.loc.start,
          end: { line: node.loc.start.line, column: node.loc.start.column + 1 },
        },
        messageId: "commentWall",
        data: { restated: String(restated), commented: String(commented) },
      });
    }

    return {
      TSInterfaceBody: check,
      TSTypeLiteral: check,
    };
  },
});
