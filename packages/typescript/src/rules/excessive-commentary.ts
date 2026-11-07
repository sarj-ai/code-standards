/**
 * @fileoverview excessive-commentary — flag long standalone implementation narration.
 *
 * Port of the 18.x `excessive-commentary` rule. The rule is untyped, so
 * the port covers all of it.
 */

import type { Comment } from "@oxlint/plugins";

import { defineRule, type Node, type SourceCode } from "../types.js";
import { parentOf } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { jsdocDecorationFix } from "../utils/jsdoc-decoration-fix.js";
import { documentsTypedFunction, proseGroups } from "../utils/prose-budget.js";

const NAME = "excessive-commentary";

const ABSOLUTE_JSDOC_LINES = 10;
const ABSOLUTE_JSDOC_WORDS = 65;
const FILE_SELF_REFERENCE_RE = /\bthis (?:file|module)\b/iu;
const CHANGE_HISTORY_RE = /\b(?:used to|previously|histor(?:y|ical)|keep moving|models? (?:move|moved|change|changed)|still under review)\b/iu;
const IMPLEMENTATION_MAP_RE = /\b(?:everything (?:above|below)|nothing else|only thing|write half|maps? between|seam between)\b/iu;

function lineCount(text: string): number {
  return text.split("\n").filter((line) => line.trim().length > 0).length;
}

function wordCount(text: string): number {
  return text.trim().split(/\s+/u).filter(Boolean).length;
}

function isJSDoc(comment: Comment): boolean {
  return comment.type === "Block" && comment.value.startsWith("*");
}

function isFileHeader(sourceCode: Readonly<SourceCode>, comment: Comment): boolean {
  return sourceCode.getTokenBefore(comment, { includeComments: false }) === null;
}

function narratesFileImplementation(text: string): boolean {
  const selfReference = FILE_SELF_REFERENCE_RE.test(text);
  const changeHistory = CHANGE_HISTORY_RE.test(text);
  const implementationMap = IMPLEMENTATION_MAP_RE.test(text);
  return (selfReference && (changeHistory || implementationMap)) || (changeHistory && implementationMap);
}

function documentsTypeOrMember(sourceCode: Readonly<SourceCode>, comment: Comment): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return false;
  for (let node = sourceCode.getNodeByRangeIndex(token.range[0]); node !== null && node.type !== "Program"; node = parentOf(node)) {
    if (isTypedDeclaration(node)) return true;
  }
  return false;
}

function isTypedDeclaration(node: Node): boolean {
  if (node.type === "ExportNamedDeclaration" || node.type === "ExportDefaultDeclaration") {
    return node.declaration !== null && isTypedDeclaration(node.declaration);
  }
  return (
    node.type === "TSInterfaceDeclaration" ||
    node.type === "TSTypeAliasDeclaration" ||
    node.type === "ClassDeclaration" ||
    node.type === "MethodDefinition" ||
    node.type === "TSMethodSignature" ||
    node.type === "TSPropertySignature"
  );
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Flag long standalone implementation commentary that should be expressed by code.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      excessive: "Implementation comment is a prose wall — make the code self-documenting and keep only durable constraints.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const sourceCode = context.sourceCode;
        for (const group of proseGroups({ filename: context.filename, cwd: context.cwd }, sourceCode)) {
          if (
            !isJSDoc(group.comment) ||
            !isFileHeader(sourceCode, group.comment) ||
            lineCount(group.text) < ABSOLUTE_JSDOC_LINES ||
            wordCount(group.text) < ABSOLUTE_JSDOC_WORDS ||
            !narratesFileImplementation(group.text) ||
            group.hasTypedTags ||
            documentsTypedFunction(sourceCode, group.comment) ||
            documentsTypeOrMember(sourceCode, group.comment)
          ) continue;
          const fix = jsdocDecorationFix(sourceCode, group.comment, (text) => lineCount(text) < ABSOLUTE_JSDOC_LINES);
          context.report({ node: group.comment, messageId: "excessive", ...(fix !== null && { fix }) });
        }
      },
    };
  },
});
