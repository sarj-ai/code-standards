/**
 * @fileoverview no-restated-comment — identify short comments that repeat adjacent statement identifiers.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-restated-comment.test.ts
 */

import { AST_NODE_TYPES, AST_TOKEN_TYPES, type TSESTree } from "@typescript-eslint/utils";

import {
  codeTokens,
  contentTokens,
  isProtected,
  restatableStatementNodeBelow,
  restates,
  restatesStatementHead,
} from "./_comments.js";
import { wholeLineRemovalRange } from "./_comment-edits.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "deleteComment" | "restatesLineBelow";
type Options = readonly [];

const MAX_WORDS = 8;
const MIN_CONTENT_TOKENS = 2;

const DIRECTIVE_RE =
  /^(eslint\b|eslint-|sarj-noqa\b|@ts-|prettier-ignore|prettier\b|biome-|c8\b|v8\b|istanbul\b|@type\b|@vite|webpack|<reference|<amd|global\b|noinspection|todo\b|fixme\b|hack\b|xxx\b)/i;

// Commented-out code and section banners belong to `no-comment-cruft`.
const CODEY_RE = /^[\w.$[\]'"]+\s*[:=]\s*\S|^[\w.$]+\s*\(|^(?:return|throw|await|import|export|const|let|var)\b.*[=()[\]{}]/;
const BANNERISH_RE = /[=\-─-╿*#~_.]{3,}|^[A-Z0-9 _:-]+$/;

const MODALITY_RE = /\b(?:can|could|should|shall|may|might|must|will|would|cannot)\b/i;
const LEAD_IN_RE = /:$/;
const EMPHASIS_RE = /\*\w[^*]*\*|`[^`]+`/;
const NEGATION_WORD_RE = /\b(?:no|not|never|neither|nor|without|none|non)\b/i;
const SEMANTIC_RELATION_RE = /\b(?:only|if|unless|when|while|except|each|every|any|all|before|after|until|since|again|once|twice|already|still|from|to|into|onto|back|versus|rather|instead)\b/i;

const ACTION_STMT_RE = /[\w.$\])]\s*\(|^\s*(?:return|throw|await|yield)\b/;

const NON_ASCII_LETTER_RE = /[^\p{ASCII}\p{N}\p{P}\p{Z}]/u;
const WALL_NARRATION_RE =
  /^(?:(?:\d+[.)]|(?:phase|step)\s+\d+\s*:?)\s*)?(?:add|build|call|check|compute|copy|count|create|fetch|filter|find|get|handle|load|map|merge|parse|process|read|remove|return|save|send|set|sort|store|update|validate|write)(?:s|es|d|ed|ing)?\b/i;
const WALL_CLUSTER_MAX_LINE_GAP = 8;
const WALL_CLUSTER_MIN_COMMENTS = 3;

export const NO_RESTATED_COMMENT_DOCUMENTATION = {
  summary: "Flag short standalone comments that repeat the adjacent statement's identifiers.",
  rationale: "A comment that only repeats code adds no context and can become stale independently.",
  remediation: "Remove a genuine restatement; retain conditions, constraints, rationale, and information absent from the statement.",
  category: "maintainability",
  autofix: "suggestion",
  limitations: [
    "Only standalone line comments of two to eight words with at least two content tokens directly above a supported single-line statement are inspected; one-word headings and sentence-ending punctuation are excluded.",
    "Evidence comes from that statement's identifier tokens, not strings, template text, comments, or neighboring statements. Stopwords and inflection folding are heuristic, not proof of semantic equivalence.",
    "Directives, protected references, conditions, restrictions, ordering, repetition, direction, questions, prose paragraphs, sibling-group labels, novel content, and generated files are excluded. Deletion is an optional suggestion, never an automatic fix.",
    "The conservative sibling-group exemption includes enclosing sibling groups and declaration/type-query pairs; it can miss genuine restatements inside those groups.",
  ],
  examples: [
    { id: "reason-comment", title: "Keep a condition the statement does not establish", outcome: "no-match", files: [{ path: "src/cache.ts", source: "// Serialize key only after validation.\nconst key = serialize(input);" }], focusPath: "src/cache.ts", expectedCount: 0, public: true },
    { id: "restated-comment", title: "Remove a comment that repeats the statement", outcome: "match", files: [{ path: "src/cache.ts", source: "// Serialize key\nconst key = serialize(input);" }], focusPath: "src/cache.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** True when `a` and `b` are `//` comments on consecutive lines. */
function areAdjacentLineComments(
  a: TSESTree.Comment | undefined,
  b: TSESTree.Comment | undefined,
  isStandalone: (comment: TSESTree.Comment) => boolean,
): boolean {
  return (
    a !== undefined &&
    b !== undefined &&
    a.type === "Line" &&
    b.type === "Line" &&
    isStandalone(a) &&
    isStandalone(b) &&
    b.loc.start.line === a.loc.end.line + 1
  );
}

function headsSiblingRun(node: TSESTree.Node): boolean {
  const parent = node.parent;
  if (parent === undefined) return false;
  const body: readonly TSESTree.Node[] | undefined =
    "body" in parent && Array.isArray(parent.body)
      ? parent.body
      : undefined;
  if (body === undefined) return false;
  const index = body.indexOf(node);
  const next = index >= 0 ? body[index + 1] : undefined;
  return next !== undefined && next.type === node.type;
}

export default createRule<Options, MessageIds>({
  name: "no-restated-comment",
  documentation: NO_RESTATED_COMMENT_DOCUMENTATION,
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    docs: {
      description: NO_RESTATED_COMMENT_DOCUMENTATION.summary,
    },
    schema: [],
    messages: {
      deleteComment: "Delete the redundant comment.",
      restatesLineBelow:
        "Comment repeats the adjacent statement's identifiers — consider removing it; retain any condition, constraint, or rationale absent from the code.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const sourceCode = context.sourceCode;

    function isStandalone(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      return !before || before.loc.end.line < comment.loc.start.line;
    }

    function labelsASiblingRun(statement: TSESTree.Node): boolean {
      for (
        let node: TSESTree.Node | undefined = statement;
        node !== undefined && node.type !== AST_NODE_TYPES.Program;
        node = node.parent
      ) {
        if (headsSiblingRun(node)) return true;
      }
      return false;
    }

    function headsValueTypeGroup(statement: TSESTree.Node): boolean {
      if (statement.type !== AST_NODE_TYPES.VariableDeclaration) return false;
      const parent = statement.parent;
      if (!("body" in parent) || !Array.isArray(parent.body)) return false;
      const body: readonly TSESTree.Node[] = parent.body;
      const next = body[body.indexOf(statement) + 1];
      if (next?.type !== AST_NODE_TYPES.TSTypeAliasDeclaration) return false;
      const names = new Set(statement.declarations.flatMap(({ id }) =>
        id.type === AST_NODE_TYPES.Identifier ? [id.name] : []));
      const tokens = sourceCode.getTokens(next);
      return tokens.some((token, index) => {
        const nextToken = tokens[index + 1];
        return token.value === "typeof" && nextToken?.type === AST_TOKEN_TYPES.Identifier &&
          names.has(nextToken.value);
      });
    }

    return {
      Program(): void {
        const comments = sourceCode.getAllComments();
        const wallMembers = new Set<TSESTree.Comment>();
        let cluster: TSESTree.Comment[] = [];
        for (const candidate of comments) {
          const body = candidate.value.replace(/^\/*/, "").trim();
          if (
            candidate.type !== "Line" ||
            !isStandalone(candidate) ||
            isProtected(body) ||
            !WALL_NARRATION_RE.test(body)
          ) {
            continue;
          }
          const previous = cluster.at(-1);
          if (
            previous !== undefined &&
            candidate.loc.start.line - previous.loc.start.line > WALL_CLUSTER_MAX_LINE_GAP
          ) {
            if (cluster.length >= WALL_CLUSTER_MIN_COMMENTS) {
              for (const member of cluster) wallMembers.add(member);
            }
            cluster = [];
          }
          cluster.push(candidate);
        }
        if (cluster.length >= WALL_CLUSTER_MIN_COMMENTS) {
          for (const member of cluster) wallMembers.add(member);
        }
        for (let i = 0; i < comments.length; i++) {
          const comment = comments[i];
          if (comment === undefined || comment.type !== "Line") continue;
          if (wallMembers.has(comment)) continue;
          if (!isStandalone(comment)) continue;
          if (
            areAdjacentLineComments(comments[i - 1], comment, isStandalone) ||
            areAdjacentLineComments(comment, comments[i + 1], isStandalone)
          ) {
            continue; // one line of a paragraph, not a label for the next statement
          }
          const body = comment.value.replace(/^\/*/, "").trim();
          if (body.length === 0 || body.endsWith("?")) continue;
          if (DIRECTIVE_RE.test(body) || CODEY_RE.test(body) || BANNERISH_RE.test(body)) continue;
          if (NON_ASCII_LETTER_RE.test(body) || isProtected(body)) continue;
          if (MODALITY_RE.test(body) || LEAD_IN_RE.test(body) || EMPHASIS_RE.test(body)) continue;
          if (NEGATION_WORD_RE.test(body) || SEMANTIC_RELATION_RE.test(body)) continue;
          const wordCount = body.split(/\s+/).length;
          if (wordCount < 2 || wordCount > MAX_WORDS || /[.!?]$/.test(body)) continue;

          const tokens = contentTokens(body);
          if (tokens.length < MIN_CONTENT_TOKENS) continue;

          const statementNode = restatableStatementNodeBelow(comment, sourceCode);
          if (statementNode === null) continue;
          const statement = sourceCode.getText(statementNode);
          if (restatesStatementHead(body, statement)) continue; // `no-comment-cruft` owns it

          if (!ACTION_STMT_RE.test(statement)) continue;

          if (labelsASiblingRun(statementNode) || headsValueTypeGroup(statementNode)) continue;

          const identifiers = sourceCode.getTokens(statementNode)
            .filter((token) => token.type === AST_TOKEN_TYPES.Identifier)
            .map((token) => token.value)
            .join(" ");
          if (restates(tokens, codeTokens(identifiers))) {
            const removal = wholeLineRemovalRange(sourceCode.text, comment);
            context.report({
              node: comment,
              messageId: "restatesLineBelow",
              suggest: removal === null
                ? null
                : [
                    {
                      messageId: "deleteComment",
                      fix: (fixer) => fixer.removeRange(removal.range),
                    },
                  ],
            });
          }
        }
      },
    };
  },
});
