/**
 * @fileoverview no-declaration-comment-wall — an enum body or class body whose member comments mostly re-spell the members is a wall the reader pays for by the block.
 *
 * Port of the 18.x `no-declaration-comment-wall` rule. File gates and
 * the comment line index move to `before()`; the judgement is unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-declaration-comment-wall.test.ts
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
  declarationRange,
  hasJsDocTag,
  isLabel,
  isTagsOnly,
  isWall,
  knownTokens,
  labelStems,
  novelWords,
} from "../utils/comment-wall.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";

/** A member this rule can judge: something with a name and a source range. */
interface Judged {
  readonly node: Node;
  readonly key: Node;
}

interface Tally {
  commented: number;
  restated: number;
  readonly removals: CommentRemoval[];
}

function named(node: Node): Judged | undefined {
  switch (node.type) {
    case "TSEnumMember":
      return { node, key: node.id };
    case "PropertyDefinition":
    case "TSAbstractPropertyDefinition":
    case "MethodDefinition":
    case "TSAbstractMethodDefinition":
      return node.computed ? undefined : { node, key: node.key };
    default:
      return undefined;
  }
}

export default defineRule({
  meta: {
    defaultOptions: [{ ...WALL_DEFAULTS }],
    type: "suggestion",
    fixable: "code",
    docs: {
      description:
        "Flag an enum body or class body whose member comments mostly re-spell the members' own names.",
      url: docsUrl("no-declaration-comment-wall"),
    },
    schema: [WALL_SCHEMA],
    messages: {
      commentWall:
        "{{restated}} of this declaration's {{commented}} member comments only re-spell member names — delete them; if a row still needs narration, give the member a clearer name. Keep constraints, lifecycle, and rationale.",
    },
  },
  createOnce(context) {
    let options: WallOptions = WALL_DEFAULTS;
    let sourceCode: SourceCode;
    // Comments indexed by the line they end on (a leading comment) and the line they start on (a trailing one).
    let endingOn = new Map<number, Comment>();
    let startingOn = new Map<number, Comment>();

    function documentingComment(member: Node): Comment | undefined {
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
            return undefined;
          }
          return lead;
        }
      }
      const trail = startingOn.get(member.loc.end.line);
      return trail !== undefined && trail.range[0] > member.range[0] ? trail : undefined;
    }

    function check(node: Node, members: readonly Node[]): void {
      const judged = members.map(named).filter((member) => member !== undefined);
      if (judged.length === 0) return;
      const { commented, restated, removals } = tally(judged);
      if (!isWall(judged.length, commented, restated, options)) return;
      context.report({
        node,
        loc: {
          start: node.loc.start,
          end: { line: node.loc.start.line, column: node.loc.start.column + 1 },
        },
        messageId: "commentWall",
        data: { restated: String(restated), commented: String(commented) },
        ...(removals.length > 0 && { fix: removalFix(sourceCode.text, removals) }),
      });
    }

    function tally(judged: readonly Judged[]): Tally {
      const documented = judged.map((member) => ({
        member,
        comment: documentingComment(member.node),
      }));
      const result: Tally = { commented: 0, restated: 0, removals: [] };
      const claimed = new Set<Comment>();
      for (const [index, { member, comment }] of documented.entries()) {
        if (comment === undefined || claimed.has(comment)) continue;
        const next = documented[index + 1];
        if (isGroupLabel(comment, member, next !== undefined && next.comment === undefined)) {
          continue;
        }
        claimed.add(comment);
        result.commented += 1;
        if (!restatesMember(comment, member)) continue;
        result.restated += 1;
        const removal = exactMemberCommentRemovalRange(sourceCode.text, comment, member.key);
        if (removal !== null) result.removals.push(removal);
      }
      return result;
    }

    function restatesMember(comment: Comment, member: Judged): boolean {
      const body = commentBody(comment);
      if (
        body.length === 0 ||
        hasJsDocTag(comment) ||
        carriesValue(body) ||
        isTagsOnly(body) ||
        isLabel(body)
      ) {
        return false;
      }
      const { end, start } = declarationRange(member.node);
      return novelWords(body, knownTokens(sourceCode.text.slice(start, end))) <= options.maxNovelWords;
    }

    function isGroupLabel(comment: Comment, member: Judged, headsRun: boolean): boolean {
      if (comment.loc.end.line >= member.node.loc.start.line) return false;
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
        if (isGeneratedFile(file, sourceCode.text) || isTestFile(file) || isStoryFile(file)) return false;
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
      ClassBody(node: ESTree.ClassBody) {
        check(node, node.body);
      },
      TSEnumDeclaration(node: ESTree.TSEnumDeclaration) {
        check(node, node.body.members);
      },
    };
  },
});

function removalFix(text: string, removals: readonly CommentRemoval[]): FixFn {
  return (fixer) => {
    const fixes: Fix[] = [];
    for (const removal of removals) {
      const endings = commentLineEndings(text, removal);
      if (endings === null) return null;
      fixes.push(fixer.replaceTextRange([...removal.range], endings));
    }
    return fixes;
  };
}
