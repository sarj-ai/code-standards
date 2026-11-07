/**
 * @fileoverview no-long-comment — catch only unusually large, unstructured JSDoc blocks.
 *
 * Port of the 18.x `no-long-comment` rule. The rule is untyped, so the
 * port covers all of it.
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type Node, type SourceCode } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { jsdocDecorationFix } from "../utils/jsdoc-decoration-fix.js";
import {
  documentsTypedFunction,
  hasDocumentationStructure,
  hasTechnicalAnchor,
  proseGroups,
  sentenceUnits,
} from "../utils/prose-budget.js";

const NAME = "no-long-comment";

const EXCESSIVE_SENTENCE_COUNT = 8;
const EXCESSIVE_WORD_COUNT = 120;
const PROSE_WORD_RE = /[\p{L}\p{N}][\p{L}\p{N}'’-]*/gu;
const VERSIONED_DEPENDENCY_TREE_RE =
  /(?:^|\/)lib\/[^/]*-?v?\d+\.\d+(?:\.\d+)?[^/]*\//iu;

const DOCUMENTED_DECLARATIONS: ReadonlySet<string> = new Set([
  "TSInterfaceDeclaration",
  "TSTypeAliasDeclaration",
  "ClassDeclaration",
  "MethodDefinition",
  "TSMethodSignature",
  "TSPropertySignature",
]);

function documentsTypeOrMember(sourceCode: Readonly<SourceCode>, comment: Comment): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return false;
  let node: Node | null | undefined = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node != null && node.type !== "Program") {
    if (DOCUMENTED_DECLARATIONS.has(node.type)) return true;
    node = node.parent;
  }
  return false;
}

function isExcessive(text: string): boolean {
  return sentenceUnits(text) >= EXCESSIVE_SENTENCE_COUNT || (text.match(PROSE_WORD_RE)?.length ?? 0) >= EXCESSIVE_WORD_COUNT;
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Flag unusually large unstructured JSDoc blocks in implementation code.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      tooLong: "Comment is an unusually large prose block — keep the local facts and clarify the code itself.",
    },
  },
  createOnce(context) {
    return {
      before() {
        if (VERSIONED_DEPENDENCY_TREE_RE.test(context.filename.replaceAll("\\", "/"))) return false;
        return undefined;
      },
      Program(): void {
        const sourceCode = context.sourceCode;
        for (const group of proseGroups({ filename: context.filename, cwd: context.cwd }, sourceCode)) {
          if (
            group.comment.type !== "Block" ||
            !group.comment.value.startsWith("*") ||
            group.hasTypedTags ||
            !isExcessive(group.text) ||
            hasDocumentationStructure(group.text) ||
            hasTechnicalAnchor(group.text) ||
            documentsTypedFunction(sourceCode, group.comment) ||
            documentsTypeOrMember(sourceCode, group.comment)
          ) continue;
          const fix = jsdocDecorationFix(sourceCode, group.comment, hasDocumentationStructure);
          context.report({ node: group.comment, messageId: "tooLong", ...(fix !== null && { fix }) });
        }
      },
    };
  },
});
