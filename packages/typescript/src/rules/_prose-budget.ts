/**
 * @fileoverview _prose-budget — shared extraction and sentence counting for comment-budget rules.
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/_prose-budget.md
 */

import { AST_NODE_TYPES, type TSESTree, type TSESLint } from "@typescript-eslint/utils";

import { isGeneratedFile, isStoryFile } from "./_paths.js";

const DIRECTIVE_RE = /^(?:!|eslint\b|eslint-|@ts-|prettier|biome-|c8\b|v8\b|istanbul\b|@vite|webpack|@jsx|@jest-environment|@vitest-environment|#__|todo\b|fixme\b|hack\b)/i;
const LICENSE_RE = /\b(?:copyright|spdx-license-identifier|licensed under)\b/i;
const TYPED_TAG_RE = /@(arg|argument|param|return|returns|yield|yields)\b/i;
const VALUE_TAG_RE = /@(example|deprecated|see|remarks|throws|internal|public|alpha|beta|since|template|fileoverview)\b/i;
const BOUNDARY_RE = /(?<=[.!?])["'`)\]]*\s+(?=[A-Z0-9`])/;
const BULLET_RE = /^\s*(?:[-*+] |\d+[.)] )/;

export interface ProseGroup {
  readonly comment: TSESTree.Comment;
  readonly text: string;
  readonly hasTypedTags: boolean;
}

function body(comment: TSESTree.Comment): string {
  return comment.value
    .replace(/^\*/, "")
    .split("\n")
    .map((line) => line.replace(/^\s*\*?\s?/, ""))
    .join("\n")
    .trim();
}

function eligible(text: string): boolean {
  return text.length > 0 && !DIRECTIVE_RE.test(text) && !LICENSE_RE.test(text) && !VALUE_TAG_RE.test(text);
}

export function sentenceUnits(text: string): number {
  const cleaned = text
    .replace(/https?:\/\/\S+/g, "URL")
    .replace(/`[^`\n]+`/g, "CODE")
    .replace(/\b\d+\.\d+\b/g, "NUMBER")
    .replace(/\b(?:e\.g\.|i\.e\.|vs\.|etc\.)/gi, "ABBREVIATION");
  let units = 0;
  const prose: string[] = [];
  for (const raw of cleaned.split("\n")) {
    const line = raw.trim();
    if (line.length === 0 || /^[A-Za-z][A-Za-z ]+:$/.test(line)) continue;
    if (BULLET_RE.test(line)) units += 1;
    else prose.push(line);
  }
  if (prose.length > 0) units += prose.join(" ").split(BOUNDARY_RE).length;
  return units;
}

export function proseGroups(
  filename: string,
  sourceCode: Readonly<TSESLint.SourceCode>,
): ProseGroup[] {
  if (isGeneratedFile(filename, sourceCode.text) || isStoryFile(filename)) return [];
  const groups: ProseGroup[] = [];
  let run: TSESTree.Comment[] = [];
  const flush = (): void => {
    if (run.length === 0) return;
    const text = run.map(body).join("\n");
    if (eligible(text)) groups.push({ comment: run[0]!, text, hasTypedTags: TYPED_TAG_RE.test(text) });
    run = [];
  };
  for (const comment of sourceCode.getAllComments()) {
    const text = body(comment);
    if (comment.type === "Block") {
      flush();
      if (eligible(text)) groups.push({ comment, text, hasTypedTags: TYPED_TAG_RE.test(text) });
      continue;
    }
    const ownLine = sourceCode.lines[comment.loc.start.line - 1]?.slice(0, comment.loc.start.column).trim() === "";
    if (!ownLine || !eligible(text)) {
      flush();
      continue;
    }
    const previous = run.at(-1);
    if (previous !== undefined && (comment.loc.start.line !== previous.loc.end.line + 1 || comment.loc.start.column !== previous.loc.start.column)) flush();
    run.push(comment);
  }
  flush();
  return groups;
}

function annotatedParameter(parameter: TSESTree.Parameter): boolean {
  if (parameter.type === AST_NODE_TYPES.TSParameterProperty) return annotatedParameter(parameter.parameter);
  const target = parameter.type === AST_NODE_TYPES.AssignmentPattern ? parameter.left : parameter;
  return "typeAnnotation" in target && target.typeAnnotation != null;
}

function typedFunction(node: TSESTree.Node): boolean {
  switch (node.type) {
    case AST_NODE_TYPES.ExportNamedDeclaration:
    case AST_NODE_TYPES.ExportDefaultDeclaration:
      return node.declaration != null && typedFunction(node.declaration);
    case AST_NODE_TYPES.FunctionDeclaration:
    case AST_NODE_TYPES.TSDeclareFunction:
      return node.returnType != null && node.params.every(annotatedParameter);
    case AST_NODE_TYPES.VariableDeclaration: {
      const init = node.declarations[0]?.init;
      return init != null &&
        (init.type === AST_NODE_TYPES.ArrowFunctionExpression || init.type === AST_NODE_TYPES.FunctionExpression) &&
        init.returnType != null && init.params.every(annotatedParameter);
    }
    case AST_NODE_TYPES.MethodDefinition:
      return node.value.returnType != null && node.value.params.every(annotatedParameter);
    case AST_NODE_TYPES.TSMethodSignature:
      return node.returnType != null && node.params.every(annotatedParameter);
    default:
      return false;
  }
}

export function documentsTypedFunction(
  sourceCode: Readonly<TSESLint.SourceCode>,
  comment: TSESTree.Comment,
): boolean {
  const token = sourceCode.getTokenAfter(comment, { includeComments: false });
  if (token === null || token.loc.start.line !== comment.loc.end.line + 1) return false;
  let node: TSESTree.Node | null = sourceCode.getNodeByRangeIndex(token.range[0]);
  while (node != null && node.type !== AST_NODE_TYPES.Program) {
    if (typedFunction(node)) return true;
    node = node.parent ?? null;
  }
  return false;
}
