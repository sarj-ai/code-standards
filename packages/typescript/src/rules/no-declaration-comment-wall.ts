/**
 * @fileoverview no-declaration-comment-wall — an enum body or class body whose member comments mostly re-spell the members is a wall the reader pays for by the block.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-declaration-comment-wall.test.ts
 */

import { AST_NODE_TYPES, AST_TOKEN_TYPES, type TSESTree } from "@typescript-eslint/utils";

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
} from "./_comment-wall.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "commentWall";

type Options = readonly [Partial<WallOptions>?];

export const noDeclarationCommentWallDocumentation = {
  summary: "Flag an enum body or class body whose member comments mostly re-spell the members' own names.",
  rationale: "A dense block of repetitive member comments obscures the few comments that add information and drifts with renamed members.",
  remediation: "Delete comments that restate member names and retain comments that explain constraints, lifecycle, or behavior.",
  category: "maintainability",
  limitations: ["Only enum and class bodies meeting the configured comment-count and restatement-ratio thresholds are reported."],
  examples: [
    {
      id: "uncommented-members",
      title: "Let clear member names stand alone",
      outcome: "no-match",
      files: [{ path: "src/status.ts", source: "enum Status { Pending = 'pending', Done = 'done', Failed = 'failed' }" }],
      focusPath: "src/status.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "restated-enum-members",
      title: "Do not restate every enum member",
      outcome: "match",
      files: [{ path: "src/status.ts", source: "enum Status {\n  /** The pending status. */\n  Pending = 'pending',\n  /** The finished status. */\n  Finished = 'finished',\n  /** The failed status. */\n  Failed = 'failed',\n}" }],
      focusPath: "src/status.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

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
  documentation: noDeclarationCommentWallDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag an enum body or class body whose member comments mostly re-spell the members' own names.",
    },
    schema: [WALL_SCHEMA],
    messages: {
      commentWall:
        "{{restated}} of this declaration's {{commented}} member comments only re-spell member names — delete them; if a row still needs narration, give the member a clearer name. Keep constraints, lifecycle, and rationale.",
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

    function documentingComment(member: TSESTree.Node): TSESTree.Comment | undefined {
      const beforeMember = sourceCode.getTokenBefore(member, { includeComments: false });
      const ownsItsLine =
        beforeMember === null || beforeMember.loc.end.line < member.loc.start.line;
      const lead = ownsItsLine ? endingOn.get(member.loc.start.line - 1) : undefined;
      if (lead !== undefined) {
        const before = sourceCode.getTokenBefore(lead, { includeComments: false });
        if (before === null || before.loc.end.line < lead.loc.start.line) {
          const previousLine = endingOn.get(lead.loc.start.line - 1);
          if (
            lead.type === AST_TOKEN_TYPES.Line &&
            previousLine?.type === AST_TOKEN_TYPES.Line &&
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
        // A tag block is a directive to a documentation generator, and one
        // content word is a label; neither is a re-spelling of the name.
        if (
          body.length === 0 ||
          hasJsDocTag(comment) ||
          carriesValue(body) ||
          isTagsOnly(body) ||
          isLabel(body)
        ) {
          continue;
        }
        const { end, start } = declarationRange(member.node);
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
