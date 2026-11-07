/**
 * @fileoverview prefer-named-complex-return-type — large inline return contracts obscure reusable domain shapes.
 *
 * Port of the 18.x `prefer-named-complex-return-type` rule. Untyped.
 * Oxlint sets an absent `returnType`/`typeArguments` to `null` where TS-ESTree
 * leaves them `undefined`; optional chaining treats both alike.
 */

import { defineRule, type Context, type ESTree, type Node } from "../types.js";
import { forEachOwnAstChild } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { existingTypeAliasFix } from "../utils/existing-type-alias-fix.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { isUnusedPrivateBinding } from "../utils/unused-private-binding.js";

const NAME = "prefer-named-complex-return-type";

type ReturnTyped =
  | ESTree.ArrowFunctionExpression
  | ESTree.Function
  | ESTree.TSMethodSignature;

function unwrap(node: ESTree.TSType): ESTree.TSType {
  if (node.type === "TSTypeReference" && node.typeArguments?.params.length === 1) {
    const [inner] = node.typeArguments.params;
    if (inner !== undefined) return unwrap(inner);
  }
  return node;
}

function report(context: Context, node: ReturnTyped): void {
  const annotation = node.returnType?.typeAnnotation;
  if (annotation === undefined || !isComplex(annotation) || hasValueDependency(annotation)) return;
  const sourceCode = context.sourceCode;
  const name =
    node.type === "FunctionDeclaration" &&
    node.id !== null &&
    isUnusedPrivateBinding(sourceCode, node, node.id, context.filename)
      ? existingTypeAliasFix(sourceCode, annotation)
      : null;
  if (name === null) {
    context.report({ node: annotation, messageId: "nameComplexReturnType" });
    return;
  }
  context.report({
    node: annotation,
    messageId: "nameComplexReturnType",
    fix: (fixer) => fixer.replaceText(annotation, name + sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")),
  });
}

function hasValueDependency(node: Node): boolean {
  return node.type === "TSThisType" || node.type === "TSTypeQuery" || forEachOwnAstChild(node, hasValueDependency);
}

function isComplex(node: ESTree.TSType): boolean {
  const type = unwrap(node);
  if (type.type === "TSTypeLiteral") return type.members.length >= 3;
  if (type.type !== "TSUnionType" || type.types.length < 3) return false;
  return type.types.every((member) => unwrap(member).type === "TSTypeLiteral");
}

export default defineRule({
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: {
      description: "Prefer a named contract for structurally complex function return types.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      nameComplexReturnType: "Extract this structurally complex return annotation to a named type or interface.",
    },
  },
  createOnce(context) {
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        return !(isTestFile(file) || isGeneratedFile(file, context.sourceCode.text));
      },
      ArrowFunctionExpression: (node) => report(context, node),
      FunctionDeclaration: (node) => report(context, node),
      FunctionExpression: (node) => report(context, node),
      TSDeclareFunction: (node) => report(context, node),
      TSMethodSignature: (node) => report(context, node),
    };
  },
});
