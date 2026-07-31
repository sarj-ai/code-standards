/**
 * @fileoverview Flag an object type whose members each carry a comment that says
 * only the member's own name and type — a wall of documentation with nothing in
 * it, reported once for the type rather than once per line.
 *
 *     interface SapCredentials {
 *       // Database host.
 *       host?: string;
 *       // Database host port.
 *       port?: number;
 *       // Database username.
 *       username?: string;
 *       // Database password.
 *       password?: string;
 *     }
 *
 * This is the **volume** rule of the comment family. Its siblings judge one
 * comment at a time and can only condemn a comment that adds *nothing*;
 * `jsdoc-restates-signature` needs every content word covered by the member's
 * name, so "Database host." on `host` is already gone but "Database host port."
 * on `port` survives on the strength of one extra word. That is the right
 * verdict for one line and the wrong verdict for ten of them: a reader scrolling
 * a forty-line interface pays for the wall, not for any single row of it. So the
 * unit of judgement here is the TYPE, and the per-comment test is deliberately
 * *looser* than a single-comment rule could justify — a comment may add up to
 * `maxNovelWords` word beyond the member's own source text and still count as
 * low-information, because it is the repetition that is being reported.
 *
 * **How the thresholds were set.** Comment density on object-type members is
 * strongly bimodal across 12 OSS TypeScript repos (excalidraw, nest, TanStack
 * Query, react-hook-form, react-router, redux-toolkit, slate, tRPC, typeorm,
 * typescript-eslint, vite, zod — 7,340 object types with 2+ members): 79% carry
 * no member comments at all and 8.6% comment EVERY member. Almost nothing sits
 * in between. "Some members are commented" is therefore not a signal — the
 * threshold that matters is not *how many* comments there are but *what they
 * say*, which is why `minRestatedRatio` and `maxNovelWords` do the work and
 * `minCommentedMembers` is only a floor (3) below which "a wall" is not a fair
 * description.
 *
 * `minCommentedRatio` (0.6) is the guard against the shape that dominated the
 * first sweep: a **group label**, one comment introducing a run of members
 * (`excalidraw/packages/excalidraw/types.ts:221` labels 6 groups inside a
 * 27-member type; `typescript-eslint/packages/ast-spec/src/expression/
 * BinaryExpression/BinaryOperatorToText.ts:4` partitions 24 operators into
 * `logical` / `bitwise` / `math`). Those comments provide the grouping and
 * deleting them loses it — the same "labels a REGION" exemption
 * `no-restated-comment` makes. Requiring the commented members to be a majority
 * of the type removes every one of them.
 *
 * **Never flagged**
 *
 * - **Generated and test files** (`_paths.isGeneratedFile` / `isTestFile`). This
 *   is not a nicety: over ten first-party repos the raw predicate found 407
 *   walls and **321 of them (79%) were OpenAPI codegen output** — one
 *   `types.gen.ts` per repo, every field carrying its own title. Editing those
 *   is work the next `openapi-generator` run reverts. The same sniff takes
 *   `jsdoc-restates-signature` "from hundreds, mostly noise, to a readable
 *   handful", and it does the same here: 407 → 86. Test files go with them: a
 *   table of identical case labels is not a documentation wall.
 * - **A member comment carrying a JSDoc value tag** (`@deprecated`, `@see`,
 *   `@example`, `@throws`, `@default`, `@remarks`, …) or a prose default
 *   (`default: true`, `defaults to …`). The default of an optional field is the
 *   one fact its type cannot hold; `vite/packages/plugin-legacy/src/types.ts:1`
 *   is eight `// default: …` rows and was the first sweep's clearest false
 *   positive.
 * - **A comment containing a digit, a unit word, a quoted example, `e.g.`, a
 *   banner rule, or a non-ASCII letter.** Each is a bound, a base, an enumerated
 *   value or prose the tokenizer cannot read — all things a name and a type
 *   cannot state. `// 0..100 (% of width)` on `x: number`, `// The 1-based
 *   column number.` on `column: number`, and `// "sukuk"` on a literal-union
 *   field were false positives until this guard existed.
 * - **Computed members.** The rule's premise is that the comment only re-spells
 *   the member's *name*; `[resultType]?: ResultType` has no readable name, and
 *   `redux-toolkit/packages/toolkit/src/query/core/endpointDefinitions.ts:520`
 *   (`// phantom type`, three times) was the last false positive this removed.
 * - **The nine-signal protected class** from `_comments`, as everywhere in this
 *   family — an exemption floor, never a test.
 *
 * **Measured.** Over the 12 OSS repos above: **8 findings**, all eight read,
 * **8 true positives, 0 false**:
 *
 * - `typeorm/src/decorator/options/JoinColumnOptions.ts:4` (3/3),
 *   `typeorm/src/metadata-args/TransactionEntityMetadataArgs.ts:4` (3/3),
 *   `typeorm/src/driver/sap/SapDataSourceOptions.ts:8` and
 *   `typeorm/src/driver/cordova/CordovaDataSourceOptions.ts:6` (3/4 each) —
 *   "Database type." on `type`, "Name of the column." on `name`.
 * - `nest/packages/common/interfaces/features/arguments-host.interface.ts:25`
 *   (3/3, "Returns the data object." on `getData()`) and
 *   `nest/packages/microservices/external/mqtt-options.interface.ts:116` (3/4,
 *   "the QoS" on `qos`, "the retain flag" on `retain`).
 * - `query/packages/lit-query/src/createInfiniteQueryController.ts:51` (3/4,
 *   "Refetches the current infinite query." on `refetch`).
 * - `react-router/packages/react-router/lib/types/route-module-annotations.ts:212`
 *   (13/14), where the comment IS the member's name — `// links`, `// meta`,
 *   `// headers`, `// clientLoader`.
 *
 * Across ten first-party repos and this repo's own `packages/typescript/src`:
 * **0 findings.** The raw predicate found 407 in those repos and every one was
 * removed by a guard that a corpus read justified — 321 (79%) by the
 * generated-file sniff and the rest by the own-line rule above. That makes this
 * a preventive ratchet rather than a migration, the SARJ051 / SARJ085 pattern:
 * a rule worth its code because it holds a line the corpus has already cleared
 * and has no failure mode surviving its exemptions.
 *
 * **Why `maxNovelWords` defaults to 1.** Loosening it to 2 takes the OSS count
 * from 8 to 34 with no clear false positive there — but it takes the
 * first-party count from 0 to 2, and BOTH are false: `name?: string; //
 * Partial match` beside `slug?: string; // Exact match` (the matching MODE is
 * the one thing neither the name nor `string` can state) and a metrics type
 * whose rows define their measure (`views: number; // unique opportunity
 * views`). Two extra words is exactly enough room for a definition. The option
 * is exposed for a team that wants the recall; the default does not take it,
 * because this rule deletes human writing and one wrong deletion is silent.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isProtected, splitIdentifier, stem } from "./_comments.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

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
  // A minority of commented members is a GROUP LABEL, not a wall — see above.
  minCommentedRatio: 0.6,
  // Room for one substantive row in four; a type where a quarter of the comments
  // say something real is a type someone was documenting, not decorating.
  minRestatedRatio: 0.75,
  // One word beyond the member's own text. Zero is `jsdoc-restates-signature`'s
  // test and is already covered there; two costs ~5% precision (see above).
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
 */
const STOPWORDS: ReadonlySet<string> = new Set(
  `the a an of to for in on with and or as at by is are was be been being
   this that it its if whether when where which what will would can could should
   must may into from over about not no does do done has have had used use uses
   using given provided specified current new existing all any each per via
   function method component hook class instance object value values data item
   items element callback handler prop props param parameter argument arg return
   returns returning result optional required true false null undefined
   string number boolean array list promise set map record type name`.split(/\s+/),
);

const WORD_RE = /[A-Za-z][A-Za-z0-9]*/g;

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
    if (isGeneratedFile(context.filename, sourceCode.text) || isTestFile(context.filename)) {
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
     * Two conditions are load-bearing and both were found by running the rule
     * over the corpus rather than by reasoning about it.
     *
     * A leading comment only counts when the MEMBER starts its own line.
     * Without that, every member of a one-line type literal claims the comment
     * that ends on the row above the whole thing — `{ d: LogoData; cids:
     * string[]; styles: LogoStyles }` under a `/** A logo. *\/` block reads as
     * three members documented three times with the same words. That shape was
     * 100% of the first-party findings before this check existed.
     *
     * And a leading comment must be alone on ITS line, or the trailing comment
     * of the previous member — which ends on exactly the row above this one — is
     * read as this member's documentation.
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

    function check(node: TSESTree.TSInterfaceBody | TSESTree.TSTypeLiteral): void {
      const members = node.type === AST_NODE_TYPES.TSInterfaceBody ? node.body : node.members;
      const named = members.filter(isNamedMember);
      if (named.length === 0) return;

      let commented = 0;
      let restated = 0;
      // A comment documents at most one member, so a shared block cannot be
      // counted once per member that happens to sit next to it.
      const claimed = new Set<TSESTree.Comment>();
      for (const member of named) {
        const comment = documentingComment(member);
        if (comment === undefined || claimed.has(comment)) continue;
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
