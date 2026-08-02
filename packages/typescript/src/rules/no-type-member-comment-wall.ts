/**
 * @fileoverview no-type-member-comment-wall — an object type whose member comments mostly re-spell the members is a wall the reader pays for by the block.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-type-member-comment-wall.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

import {
  BARE_LABEL_RE,
  WALL_DEFAULTS,
  WALL_SCHEMA,
  type WallOptions,
  carriesValue,
  commentBody,
  isWall,
  knownTokens,
  labelStems,
  novelWords,
} from "./_comment-wall.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "commentWall";

type Options = readonly [Partial<WallOptions>?];

/** A member the rule can judge: a named property or method signature. */
type NamedMember = TSESTree.TSPropertySignature | TSESTree.TSMethodSignature;

function isNamedMember(node: TSESTree.TypeElement): node is NamedMember {
  return (
    (node.type === AST_NODE_TYPES.TSPropertySignature ||
      node.type === AST_NODE_TYPES.TSMethodSignature) &&
    !node.computed
  );
}

export default createRule<Options, MessageIds>({
  name: "no-type-member-comment-wall",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag an object type whose member comments mostly re-spell the members' own names and types.",
    },
    schema: [WALL_SCHEMA],
    messages: {
      commentWall:
        "{{restated}} of this type's {{commented}} member comments only re-spell the member's own name and type — delete them, and keep the rows that say what the name cannot.",
    },
  },
  defaultOptions: [WALL_DEFAULTS],
  create(context, [provided]) {
    const options: WallOptions = { ...WALL_DEFAULTS, ...provided };
    const sourceCode = context.sourceCode;
    // Generated or vendored, a test fixture, or a demo story: three kinds of
    // file whose member comments are output rather than commentary.
    if (
      isGeneratedFile(context.filename, sourceCode.text, ["externalTree"]) ||
      isTestFile(context.filename, ["fixtureTree"]) ||
      isStoryFile(context.filename, ["storyTree"])
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

      if (!isWall(named.length, commented, restated, options)) return;
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
