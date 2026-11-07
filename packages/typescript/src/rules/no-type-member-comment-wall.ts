/**
 * @fileoverview no-type-member-comment-wall — an object type whose member comments mostly re-spell the members' names and types is a wall the reader pays for by the block.
 *
 * Port of the 18.x `no-type-member-comment-wall` rule. File gates and
 * the comment line index move to `before()`; the judgement is unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-type-member-comment-wall.test.ts
 */

import type { Comment, Fix, FixFn } from "@oxlint/plugins";

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { commentLineEndings, exactMemberCommentRemovalRange, type CommentRemoval } from "../utils/comment-edits.js";
import {
  BARE_LABEL_RE,
  WALL_DEFAULTS,
  WALL_SCHEMA,
  type WallOptions,
  carriesValue,
  commentBody,
  hasJsDocTag,
  isTagsOnly,
  isWall,
  knownTokens,
  labelStems,
  novelWords,
} from "../utils/comment-wall.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";

const BEHAVIORAL_RELATION_RE = /\b(?:not|no|never|only|must|shall|should|may|can|could|will|would|required|optional|if|unless|when|before|after|until|while|without|instead|true|false|null|undefined)\b|[<>=!]/iu;

/** A member the rule can judge: a named property or method signature. */
type NamedMember = ESTree.TSPropertySignature | ESTree.TSMethodSignature;

/** Comments that document a member, and the restating ones among them with their exact removals. */
interface Tally {
  readonly commented: number;
  readonly restated: number;
  readonly removals: readonly CommentRemoval[];
}

export default defineRule({
  meta: {
    defaultOptions: [{ ...WALL_DEFAULTS }],
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Flag an object type whose member comments mostly re-spell the members' own names and types.",
      url: docsUrl("no-type-member-comment-wall"),
    },
    schema: [WALL_SCHEMA],
    messages: {
      commentWall:
        "{{restated}} of this type's {{commented}} member comments appear to repeat names and types — review them for removal or clearer naming. Keep constraints and rationale.",
    },
  },
  createOnce(context) {
    let options: WallOptions = WALL_DEFAULTS;
    let sourceCode: SourceCode;
    // Comments indexed by the line they end on (a leading comment) and the line they start on (a trailing one).
    let endingOn = new Map<number, Comment>();
    let startingOn = new Map<number, Comment>();

    function documentingComment(member: NamedMember): Comment | undefined {
      const beforeMember = sourceCode.getTokenBefore(member, { includeComments: false });
      const ownsItsLine =
        beforeMember === null || beforeMember.loc.end.line < member.loc.start.line;
      const lead = ownsItsLine ? endingOn.get(member.loc.start.line - 1) : undefined;
      if (lead !== undefined) {
        const before = sourceCode.getTokenBefore(lead, { includeComments: false });
        if (before === null || before.loc.end.line < lead.loc.start.line) {
          const previousLine = endingOn.get(lead.loc.start.line - 1);
          if (
            lead.type === "Line" &&
            previousLine?.type === "Line" &&
            previousLine.loc.start.column === lead.loc.start.column
          ) {
            // The final row alone can omit rationale carried above it, so leave a multi-line block unjudged.
            return undefined;
          }
          return lead;
        }
      }
      const trail = startingOn.get(member.loc.end.line);
      return trail !== undefined && trail.range[0] > member.range[0] ? trail : undefined;
    }

    function check(node: ESTree.TSInterfaceBody | ESTree.TSTypeLiteral): void {
      const members: readonly Node[] = node.type === "TSInterfaceBody" ? node.body : node.members;
      const named = members.flatMap((member) =>
        (member.type === "TSPropertySignature" || member.type === "TSMethodSignature") && !member.computed ? [member] : []);
      if (named.length === 0) return;
      const { commented, restated, removals } = tally(named);
      if (!isWall(named.length, commented, restated, options)) return;
      const fix: FixFn = (fixer) => {
        const fixes: Fix[] = [];
        for (const removal of removals) {
          const endings = commentLineEndings(sourceCode.text, removal);
          if (endings === null) return null;
          fixes.push(fixer.replaceTextRange([...removal.range], endings));
        }
        return fixes;
      };
      context.report({
        node,
        loc: {
          start: node.loc.start,
          end: { line: node.loc.start.line, column: node.loc.start.column + 1 },
        },
        messageId: "commentWall",
        data: { restated: String(restated), commented: String(commented) },
        ...(removals.length > 0 && { fix }),
      });
    }

    /** Count the members' own comments, and those that only re-spell the member. */
    function tally(named: readonly NamedMember[]): Tally {
      const documented = named.map((member) => ({ member, comment: documentingComment(member) }));
      let commented = 0;
      let restated = 0;
      const removals: CommentRemoval[] = [];
      // A comment documents at most one member.
      const claimed = new Set<Comment>();
      for (const [index, { member, comment }] of documented.entries()) {
        if (comment === undefined || claimed.has(comment)) continue;
        const next = documented[index + 1];
        if (isGroupLabel(comment, member, next !== undefined && next.comment === undefined)) continue;
        claimed.add(comment);
        commented += 1;
        if (restatesMember(comment, member)) {
          restated += 1;
          const removal = exactMemberCommentRemovalRange(sourceCode.text, comment, member.key);
          if (removal !== null) removals.push(removal);
        }
      }
      return { commented, restated, removals };
    }

    function restatesMember(comment: Comment, member: NamedMember): boolean {
      const body = commentBody(comment);
      return body.length > 0 && !hasJsDocTag(comment) && !carriesValue(body) && !isTagsOnly(body) && !BEHAVIORAL_RELATION_RE.test(body) &&
        novelWords(body, knownTokens(sourceCode.getText(member))) <= options.maxNovelWords;
    }

    function isGroupLabel(comment: Comment, member: NamedMember, headsRun: boolean): boolean {
      if (comment.loc.end.line >= member.loc.start.line) return false;
      const body = commentBody(comment);
      if (!BARE_LABEL_RE.test(body)) return false;
      if (labelStems(body) === labelStems(sourceCode.getText(member.key))) return false;
      const lineAbove = sourceCode.lines[comment.loc.start.line - 2];
      return headsRun || (lineAbove !== undefined && lineAbove.trim().length === 0);
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        // Generated or vendored, a test fixture, or a demo story: member comments there are output rather than commentary.
        if (
          isGeneratedFile(file, sourceCode.text, ["externalTree"]) ||
          isTestFile(file, ["fixtureTree"]) ||
          isStoryFile(file, ["storyTree"])
        ) {
          return false;
        }
        const [provided] = context.options as unknown as readonly [Partial<WallOptions>?];
        options = { ...WALL_DEFAULTS, ...provided };
        endingOn = new Map();
        startingOn = new Map();
        for (const comment of sourceCode.getAllComments()) {
          endingOn.set(comment.loc.end.line, comment);
          if (!startingOn.has(comment.loc.start.line)) startingOn.set(comment.loc.start.line, comment);
        }
        return undefined;
      },
      TSInterfaceBody: check,
      TSTypeLiteral: check,
    };
  },
});
