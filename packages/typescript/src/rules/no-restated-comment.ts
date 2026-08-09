/**
 * @fileoverview no-restated-comment — a comment whose every content word is already on the line below can only go out of date silently.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-restated-comment.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import {
  codeTokens,
  contentTokens,
  isProtected,
  restatableStatementBelow,
  restates,
  restatesStatementHead,
} from "./_comments.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "restatesLineBelow";
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

const ACTION_STMT_RE = /[\w.$\])]\s*\(|^\s*(?:return|throw|await|yield)\b/;

const NON_ASCII_LETTER_RE = /[^\p{ASCII}\p{N}\p{P}\p{Z}]/u;
const WALL_NARRATION_RE =
  /^(?:(?:\d+[.)]|(?:phase|step)\s+\d+\s*:?)\s*)?(?:add|build|call|check|compute|copy|count|create|fetch|filter|find|get|handle|load|map|merge|parse|process|read|remove|return|save|send|set|sort|store|update|validate|write)(?:s|es|d|ed|ing)?\b/i;
const WALL_CLUSTER_MAX_LINE_GAP = 8;
const WALL_CLUSTER_MIN_COMMENTS = 3;

export const noRestatedCommentDocumentation = {
  summary: "Flag a single-line comment whose every word already appears on the statement below it.",
  rationale: "A comment that only repeats code adds no context and can become stale independently.",
  remediation: "Delete the comment or replace it with the reason, constraint, or consequence absent from the code.",
  category: "maintainability",
  limitations: ["Directives, protected references, questions, multi-line prose, comments with novel content, and generated files are excluded."],
  examples: [
    { id: "reason-comment", title: "Keep the reason the code cannot express", outcome: "no-match", files: [{ path: "src/cache.ts", source: "// Serialize because the cache key is stable across deploys.\nconst key = serialize(input);" }], focusPath: "src/cache.ts", expectedCount: 0, public: true },
    { id: "restated-comment", title: "Remove a comment that repeats the statement", outcome: "match", files: [{ path: "src/cache.ts", source: "// Serialize key\nconst key = serialize(input);" }], focusPath: "src/cache.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

/** True when `a` and `b` are `//` comments on consecutive lines. */
function areAdjacentLineComments(
  a: TSESTree.Comment | undefined,
  b: TSESTree.Comment | undefined,
): boolean {
  return (
    a !== undefined &&
    b !== undefined &&
    a.type === "Line" &&
    b.type === "Line" &&
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
  documentation: noRestatedCommentDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Flag a single-line comment whose every word already appears on the statement below it.",
    },
    schema: [],
    messages: {
      restatesLineBelow:
        "Comment restates the statement below it — delete it, or replace it with the *why*; the code already carries the *what*.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    const sourceCode = context.sourceCode;
    const lines = sourceCode.lines;

    function isStandalone(comment: TSESTree.Comment): boolean {
      const before = sourceCode.getTokenBefore(comment, { includeComments: false });
      return !before || before.loc.end.line < comment.loc.start.line;
    }

    function labelsASiblingRun(comment: TSESTree.Comment): boolean {
      const token = sourceCode.getTokenAfter(comment, { includeComments: false });
      if (token === null) return false;
      for (
        let node: TSESTree.Node | undefined | null = sourceCode.getNodeByRangeIndex(token.range[0]);
        node != null && node.type !== AST_NODE_TYPES.Program;
        node = node.parent
      ) {
        if (headsSiblingRun(node)) return true;
      }
      return false;
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
            areAdjacentLineComments(comments[i - 1], comment) ||
            areAdjacentLineComments(comment, comments[i + 1])
          ) {
            continue; // one line of a paragraph, not a label for the next statement
          }
          const body = comment.value.replace(/^\/*/, "").trim();
          if (body.length === 0 || body.endsWith("?")) continue;
          if (DIRECTIVE_RE.test(body) || CODEY_RE.test(body) || BANNERISH_RE.test(body)) continue;
          if (NON_ASCII_LETTER_RE.test(body) || isProtected(body)) continue;
          if (MODALITY_RE.test(body) || LEAD_IN_RE.test(body) || EMPHASIS_RE.test(body)) continue;
          if (NEGATION_WORD_RE.test(body)) continue;
          if (body.split(/\s+/).length > MAX_WORDS) continue;

          const tokens = contentTokens(body);
          if (tokens.length < MIN_CONTENT_TOKENS) continue;

          const statement = restatableStatementBelow(comment, sourceCode);
          if (statement === null) continue;
          if (restatesStatementHead(body, statement)) continue; // `no-comment-cruft` owns it

          const line = lines[comment.loc.start.line] ?? "";
          if (!ACTION_STMT_RE.test(line)) continue;

          if (labelsASiblingRun(comment)) continue;

          if (restates(tokens, codeTokens(line))) {
            context.report({ node: comment, messageId: "restatesLineBelow" });
          }
        }
      },
    };
  },
});
