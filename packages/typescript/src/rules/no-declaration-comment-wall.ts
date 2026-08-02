/**
 * @fileoverview no-declaration-comment-wall — an enum body or class body whose member comments mostly re-spell the members is a wall the reader pays for by the block.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-declaration-comment-wall.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import {
  BARE_LABEL_RE,
  WALL_DEFAULTS,
  WALL_SCHEMA,
  type WallOptions,
  carriesValue,
  commentBody,
  declarationRange,
  isLabel,
  isTagsOnly,
  isWall,
  knownTokens,
  labelStems,
  novelWords,
} from "./_comment-wall.js";
import { createRule } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "commentWall";

type Options = readonly [Partial<WallOptions>?];

/** A member this rule can judge: something with a name and a source range. */
interface Judged {
  readonly node: TSESTree.Node;
  readonly key: TSESTree.Node;
}

function named(node: TSESTree.Node): Judged | undefined {
  switch (node.type) {
    case AST_NODE_TYPES.TSEnumMember:
      return { node, key: node.id };
    case AST_NODE_TYPES.PropertyDefinition:
    case AST_NODE_TYPES.TSAbstractPropertyDefinition:
    case AST_NODE_TYPES.MethodDefinition:
    case AST_NODE_TYPES.TSAbstractMethodDefinition:
      return node.computed ? undefined : { node, key: node.key };
    default:
      return undefined;
  }
}

export default createRule<Options, MessageIds>({
  name: "no-declaration-comment-wall",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag an enum body or class body whose member comments mostly re-spell the members' own names.",
    },
    schema: [WALL_SCHEMA],
    messages: {
      commentWall:
        "{{restated}} of this declaration's {{commented}} member comments only re-spell the member's own name — delete them, and keep the rows that say what the name cannot.",
    },
  },
  defaultOptions: [WALL_DEFAULTS],
  create(context, [provided]) {
    const options: WallOptions = { ...WALL_DEFAULTS, ...provided };
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
     * only when the comment is alone on ITS line; a trailing comment counts only
     * when it sits after the member it is read against. Between them no comment
     * can document two members, which is why this rule needs no claim set.
     */
    function documentingComment(member: TSESTree.Node): TSESTree.Comment | undefined {
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
     * True when a comment heads a REGION instead of describing the member under
     * it. The body is ONE bare identifier word; it names something OTHER than
     * the member below it; and it shows region evidence, heading a run of
     * members of which only the first is commented, or set off by a blank line.
     */
    function isGroupLabel(comment: TSESTree.Comment, member: Judged, headsRun: boolean): boolean {
      if (comment.loc.end.line >= member.node.loc.start.line) return false;
      const body = commentBody(comment);
      if (!BARE_LABEL_RE.test(body)) return false;
      if (labelStems(body) === labelStems(sourceCode.getText(member.key))) return false;
      const lineAbove = sourceCode.lines[comment.loc.start.line - 2];
      return headsRun || (lineAbove !== undefined && lineAbove.trim().length === 0);
    }

    function check(node: TSESTree.Node, members: readonly TSESTree.Node[]): void {
      const judged = members.map(named).filter((member): member is Judged => member !== undefined);
      if (judged.length === 0) return;

      const documented = judged.map((member) => ({
        member,
        comment: documentingComment(member.node),
      }));
      let commented = 0;
      let restated = 0;
      for (const [index, { member, comment }] of documented.entries()) {
        if (comment === undefined) continue;
        const next = documented[index + 1];
        if (isGroupLabel(comment, member, next !== undefined && next.comment === undefined)) {
          continue;
        }
        commented += 1;
        const body = commentBody(comment);
        // A tag block is a directive to a documentation generator, and one
        // content word is a label; neither is a re-spelling of the name.
        if (body.length === 0 || carriesValue(body) || isTagsOnly(body) || isLabel(body)) {
          continue;
        }
        const [start, end] = declarationRange(member.node);
        if (novelWords(body, knownTokens(sourceCode.text.slice(start, end))) <= options.maxNovelWords) {
          restated += 1;
        }
      }

      if (!isWall(judged.length, commented, restated, options)) return;
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
      ClassBody: (node: TSESTree.ClassBody) => {
        check(node, node.body);
      },
      TSEnumDeclaration: (node: TSESTree.TSEnumDeclaration) => {
        check(node, node.body.members);
      },
    };
  },
});
