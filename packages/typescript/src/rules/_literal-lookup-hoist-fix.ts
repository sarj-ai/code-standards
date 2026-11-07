/** @fileoverview _literal-lookup-hoist-fix — hoist a private readonly literal lookup. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { getPropertyName } from "../utils/static-string.js";
import { soleConstDeclarator, soleExportedFunction } from "./_closed-module.js";

/** A sole module entry reads its private readonly literal lookup only through native includes. */
export function literalLookupHoistFix(sourceCode: SourceCode, node: ESTree.VariableDeclarator): FixFn | null {
  if (
    node.id.type !== "Identifier" ||
    !readonlyStrings(node.id.typeAnnotation?.typeAnnotation) ||
    node.init?.type !== "ArrayExpression" ||
    !node.init.elements.every((element) => element?.type === "Literal" && typeof element.value === "string")
  )
    return null;
  const collection = node.id.name;
  const entry = soleExportedFunction(sourceCode);
  if (entry === null || entry.owner.id?.name === collection || entry.owner.params.length !== 1 || entry.body.length !== 2)
    return null;
  const { statement, owner } = entry;
  const [argument] = owner.params;
  const [declaration, returned] = entry.body;
  if (
    argument?.type !== "Identifier" ||
    argument.optional ||
    argument.name === collection ||
    argument.typeAnnotation?.typeAnnotation.type !== "TSStringKeyword" ||
    declaration?.type !== "VariableDeclaration" ||
    soleConstDeclarator(declaration) !== node ||
    returned?.type !== "ReturnStatement" ||
    (isPresent(owner.returnType) && owner.returnType.typeAnnotation.type !== "TSBooleanKeyword") ||
    !includesArgument(returned.argument, collection, argument.name)
  )
    return null;
  const newline = sourceCode.text.includes("\r\n") ? "\r\n" : "\n";
  return (fixer) => [
    fixer.insertTextBefore(statement, `${sourceCode.getText(declaration)}${newline}`),
    fixer.removeRange([declaration.range[0], returned.range[0]]),
  ];
}

function readonlyStrings(node: ESTree.TSType | null | undefined): boolean {
  return (
    node?.type === "TSTypeOperator" &&
    node.operator === "readonly" &&
    node.typeAnnotation?.type === "TSArrayType" &&
    node.typeAnnotation.elementType.type === "TSStringKeyword"
  );
}

function includesArgument(node: Node | null | undefined, collection: string, argument: string): boolean {
  if (
    node?.type !== "CallExpression" ||
    node.optional ||
    node.arguments.length !== 1 ||
    node.callee.type !== "MemberExpression" ||
    node.callee.optional
  )
    return false;
  const member = node.callee;
  const value = node.arguments[0];
  return (
    member.object.type === "Identifier" &&
    member.object.name === collection &&
    getPropertyName(member) === "includes" &&
    value?.type === "Identifier" &&
    value.name === argument
  );
}
