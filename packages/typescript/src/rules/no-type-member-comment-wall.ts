/**
 * @fileoverview no-type-member-comment-wall — an object type whose member comments mostly re-spell the members is a wall the reader pays for by the block.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-type-member-comment-wall.test.ts
 */

import { AST_NODE_TYPES, AST_TOKEN_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

import {
  BARE_LABEL_RE,
  WALL_DEFAULTS,
  WALL_SCHEMA,
  type WallOptions,
  carriesValue,
  commentBody,
  hasJsDocTag,
  isWall,
  isTagsOnly,
  knownTokens,
  labelStems,
  novelWords,
} from "./_comment-wall.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "commentWall";

type Options = readonly [Partial<WallOptions>?];

export const noTypeMemberCommentWallDocumentation = {
  summary: "Flag an object type whose member comments mostly re-spell the members' own names and types.",
  rationale: "Repetitive member comments add scanning cost while hiding the comments that describe facts absent from the type.",
  remediation: "Delete comments that restate member names or types and keep comments that add constraints or behavior.",
  category: "maintainability",
  limitations: ["Only interface and type-literal bodies meeting the configured comment-count and restatement-ratio thresholds are reported."],
  examples: [
    {
      id: "uncommented-members",
      title: "Let clear member names and types stand alone",
      outcome: "no-match",
      files: [{ path: "src/credentials.ts", source: "interface Credentials { host: string; port: number; username: string; }" }],
      focusPath: "src/credentials.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "restated-type-members",
      title: "Do not restate member names and types",
      outcome: "match",
      files: [{ path: "src/credentials.ts", source: "interface Credentials {\n  // Database host.\n  host?: string;\n  // Database host port.\n  port?: number;\n  // Database username.\n  username?: string;\n  // Database password.\n  password?: string;\n}" }],
      focusPath: "src/credentials.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

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
  documentation: noTypeMemberCommentWallDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag an object type whose member comments mostly re-spell the members' own names and types.",
    },
    schema: [WALL_SCHEMA],
    messages: {
      commentWall:
        "{{restated}} of this type's {{commented}} member comments only re-spell names and types — delete them; if a row still needs narration, improve its name or type. Keep constraints and rationale.",
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

    function documentingComment(member: NamedMember): TSESTree.Comment | undefined {
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
            // The final row alone can omit rationale carried above it, so leave
            // a multi-line block unjudged instead of scoring a partial comment.
            return undefined;
          }
          return lead;
        }
      }
      const trail = startingOn.get(member.loc.end.line);
      return trail !== undefined && trail.range[0] > member.range[0] ? trail : undefined;
    }

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
        if (body.length === 0 || hasJsDocTag(comment) || carriesValue(body) || isTagsOnly(body)) {
          continue;
        }
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
