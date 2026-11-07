/** @fileoverview _literal-identity-reduce-fix — remove unobservable identity-reducer copies. */

import type { Fixer, Fix } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { soleExportedFunction } from "./_closed-module.js";

export type ReduceFix = (fixer: Fixer) => Fix;

/** Returning a fresh primitive array needs none of an unobservable identity reducer's copies. */
export function literalIdentityReduceFix(sourceCode: Readonly<SourceCode>, node: ESTree.CallExpression): ReduceFix | null {
  if (
    node.optional ||
    node.arguments.length !== 2 ||
    node.callee.type !== "MemberExpression" ||
    node.callee.optional ||
    getPropertyName(node.callee) !== "reduce" ||
    node.typeArguments?.params.length !== 1 ||
    !stringArray(node.typeArguments.params[0])
  ) return null;
  const values = node.callee.object;
  if (
    values.type !== "ArrayExpression" ||
    values.elements.length === 0 ||
    !values.elements.every((element) => element?.type === "Literal" && typeof element.value === "string")
  ) return null;
  const entry = soleExportedFunction(sourceCode);
  if (
    entry === null ||
    entry.owner.params.length !== 0 ||
    !stringArray(entry.owner.returnType?.typeAnnotation) ||
    entry.body.length !== 1 ||
    entry.body[0]?.type !== "ReturnStatement" ||
    entry.body[0].argument !== node
  ) return null;
  const [callback, seed] = node.arguments;
  if (
    seed?.type !== "ArrayExpression" ||
    seed.elements.length !== 0 ||
    callback?.type !== "ArrowFunctionExpression" ||
    callback.async ||
    isPresent(callback.typeParameters) ||
    isPresent(callback.returnType) ||
    callback.params.length !== 2 ||
    callback.body.type !== "ArrayExpression" ||
    callback.body.elements.length !== 2 ||
    !identitySpread(sourceCode, callback)
  ) return null;
  return (fixer) => fixer.replaceText(node, sourceCode.getText(values));
}

function stringArray(node: Node | null | undefined): boolean {
  return node?.type === "TSArrayType" && node.elementType.type === "TSStringKeyword";
}

function identitySpread(sourceCode: Readonly<SourceCode>, callback: ESTree.ArrowFunctionExpression): boolean {
  const [accumulator, item] = callback.params;
  if (
    accumulator?.type !== "Identifier" ||
    item?.type !== "Identifier" ||
    accumulator.name === item.name ||
    accumulator.optional ||
    item.optional ||
    isPresent(accumulator.typeAnnotation) ||
    isPresent(item.typeAnnotation) ||
    callback.body.type !== "ArrayExpression"
  ) return false;
  const [spread, appended] = callback.body.elements;
  if (
    spread?.type !== "SpreadElement" ||
    spread.argument.type !== "Identifier" ||
    appended?.type !== "Identifier" ||
    spread.argument.name !== accumulator.name ||
    appended.name !== item.name
  ) return false;
  const bindings = sourceCode.getDeclaredVariables(callback);
  const left = bindings.find((variable) => variable.identifiers.includes(accumulator as never));
  const right = bindings.find((variable) => variable.identifiers.includes(item as never));
  return left !== undefined && right !== undefined &&
    findVariable(sourceCode.getScope(spread.argument), spread.argument.name) === left &&
    findVariable(sourceCode.getScope(appended), appended.name) === right;
}
