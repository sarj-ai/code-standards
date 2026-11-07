/**
 * @fileoverview no-restated-comment — short standalone comments that only repeat the adjacent statement.
 *
 * Port of the 18.x `no-restated-comment` rule. The rule is untyped, so
 * the port covers all of it.
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type Node } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { commentLineEndings, wholeLineRemovalRange } from "../utils/comment-edits.js";
import {
  codeTokens,
  contentTokens,
  isProtected,
  restatableStatementNodeBelow,
  restates,
  restatesStatementHead,
} from "../utils/comments.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile } from "../utils/paths.js";

const NAME = "no-restated-comment";

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

const SENTENCE_END_RE = /[.!?]$/;
const NON_LABEL_RES: readonly RegExp[] = [
  DIRECTIVE_RE, CODEY_RE, BANNERISH_RE, NON_ASCII_LETTER_RE, MODALITY_RE,
  LEAD_IN_RE, EMPHASIS_RE, NEGATION_WORD_RE, SEMANTIC_RELATION_RE,
];

/** Indices of standalone narration comments in clusters of at least three, each within eight lines of the last. */
function narrationWalls(comments: readonly Comment[], standalone: readonly boolean[], bodies: readonly string[]): Set<number> {
  const members = new Set<number>();
  let cluster: number[] = [];
  const close = (): void => {
    if (cluster.length >= WALL_CLUSTER_MIN_COMMENTS) for (const member of cluster) members.add(member);
    cluster = [];
  };
  comments.forEach((comment, i) => {
    if (!standalone[i] || isProtected(bodies[i] ?? "") || !WALL_NARRATION_RE.test(bodies[i] ?? "")) return;
    const previous = comments[cluster.at(-1) ?? -1];
    if (previous !== undefined && comment.loc.start.line - previous.loc.start.line > WALL_CLUSTER_MAX_LINE_GAP) close();
    cluster.push(i);
  });
  close();
  return members;
}

function siblingBody(parent: Node): readonly Node[] | undefined {
  const body: unknown = "body" in parent ? parent.body : undefined;
  return Array.isArray(body) ? (body as readonly Node[]) : undefined;
}

function headsSiblingRun(node: Node): boolean {
  const parent = parentOf(node);
  if (parent === null) return false;
  const body = siblingBody(parent);
  if (body === undefined) return false;
  const index = body.indexOf(node);
  const next = index >= 0 ? body[index + 1] : undefined;
  return next !== undefined && next.type === node.type;
}

export default defineRule({
  meta: {
    type: "suggestion",
    hasSuggestions: true,
    fixable: "code",
    docs: {
      description: "Flag short standalone comments that repeat the adjacent statement's identifiers.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      deleteComment: "Delete the redundant comment.",
      restatesLineBelow:
        "Comment repeats the adjacent statement's identifiers — consider removing it; retain any condition, constraint, or rationale absent from the code.",
    },
  },
  createOnce(context) {
    function isStandalone(comment: Comment): boolean {
      const before = context.sourceCode.getTokenBefore(comment, { includeComments: false });
      return !before || before.loc.end.line < comment.loc.start.line;
    }

    function labelsASiblingRun(statement: Node): boolean {
      for (let node: Node | null = statement; node !== null && node.type !== "Program"; node = parentOf(node)) {
        if (headsSiblingRun(node)) return true;
      }
      return false;
    }

    function headsValueTypeGroup(statement: Node): boolean {
      if (statement.type !== "VariableDeclaration") return false;
      const parent = parentOf(statement);
      if (parent === null) return false;
      const body = siblingBody(parent);
      if (body === undefined) return false;
      const next = body[body.indexOf(statement) + 1];
      if (next?.type !== "TSTypeAliasDeclaration") return false;
      const names = new Set(statement.declarations.flatMap(({ id }) => (id.type === "Identifier" ? [id.name] : [])));
      const tokens = context.sourceCode.getTokens(next);
      return tokens.some((token, index) => {
        const nextToken = tokens[index + 1];
        return token.value === "typeof" && nextToken?.type === "Identifier" && names.has(nextToken.value);
      });
    }

    function reportRestated(comment: Comment): void {
      const text = context.sourceCode.text;
      const removal = wholeLineRemovalRange(text, comment);
      if (removal === null) {
        context.report({ node: comment, messageId: "restatesLineBelow" });
        return;
      }
      context.report({
        node: comment,
        messageId: "restatesLineBelow",
        fix: (fixer) => {
          const endings = commentLineEndings(text, removal);
          return endings === null ? null : fixer.replaceTextRange([removal.range[0], removal.range[1]], endings);
        },
        suggest: [
          {
            messageId: "deleteComment",
            fix: (fixer) => fixer.removeRange([removal.range[0], removal.range[1]]),
          },
        ],
      });
    }

    return {
      before() {
        if (isGeneratedFile({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text)) return false;
        return undefined;
      },
      Program(): void {
        const sourceCode = context.sourceCode;
        const comments = sourceCode.getAllComments();
        // Only standalone `//` comments can label a statement, join a paragraph or form a narration wall.
        const standalone = comments.map((comment) => comment.type === "Line" && isStandalone(comment));
        const bodies = comments.map((comment) => comment.value.replace(/^\/*/, "").trim());
        const wallMembers = narrationWalls(comments, standalone, bodies);
        function checkComment(comment: Comment, i: number): void {
          // A line of a paragraph is not a label for the next statement.
          if (!standalone[i] || wallMembers.has(i) || adjacent(i - 1, i) || adjacent(i, i + 1)) return;
          const body = bodies[i] ?? "";
          if (!isRestatableLabel(body)) return;
          const tokens = contentTokens(body);
          if (tokens.length < MIN_CONTENT_TOKENS) return;
          const statementNode = restatableStatementNodeBelow(comment, sourceCode);
          if (statementNode === null) return;
          const statement = sourceCode.getText(statementNode);
          // `no-comment-cruft` owns a comment that restates the statement head.
          if (restatesStatementHead(body, statement) || !ACTION_STMT_RE.test(statement) ||
            labelsASiblingRun(statementNode) || headsValueTypeGroup(statementNode)) return;
          const identifiers = sourceCode.getTokens(statementNode)
            .filter((token) => token.type === "Identifier")
            .map((token) => token.value)
            .join(" ");
          if (restates(tokens, codeTokens(identifiers))) reportRestated(comment);
        }

        /** True when comments `a` and `b` are standalone `//` comments on consecutive lines. */
        function adjacent(a: number, b: number): boolean {
          const upper = comments[a];
          const lower = comments[b];
          return upper !== undefined && lower !== undefined && standalone[a] === true && standalone[b] === true &&
            lower.loc.start.line === upper.loc.end.line + 1;
        }

        comments.forEach(checkComment);
      },
    };
  },
});

function isRestatableLabel(body: string): boolean {
  if (isProtected(body) || NON_LABEL_RES.some((pattern) => pattern.test(body))) return false;
  const wordCount = body.split(/\s+/).length;
  return wordCount >= 2 && wordCount <= MAX_WORDS && !SENTENCE_END_RE.test(body);
}
