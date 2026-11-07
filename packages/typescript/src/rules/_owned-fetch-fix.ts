/** @fileoverview _owned-fetch-fix — repair the receiver of one owned literal request. */

import type { FixFn } from "@oxlint/plugins";

import type { ESTree, Node, SourceCode } from "../types.js";
import { isPresent } from "../utils/is-present.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { soleConstDeclarator, soleExportedFunction } from "./_closed-module.js";

/** Repair a receiver only when the private stored callable is used by one literal request. */
export function ownedFetchFix(sourceCode: SourceCode, node: Node): FixFn | null {
  if (node.type !== "Identifier" || node.name !== "fetch" || isShadowed(sourceCode, node, "fetch") ||
    isShadowed(sourceCode, node, "undefined")) return null;
  const entry = soleExportedFunction(sourceCode);
  if (entry === null || entry.owner.params.length !== 0 || isPresent(entry.owner.returnType) || entry.body.length !== 2)
    return null;
  const [declaration, returned] = entry.body;
  if (declaration?.type !== "VariableDeclaration" || returned?.type !== "ReturnStatement") return null;
  const object = soleConstDeclarator(declaration);
  if (
    object?.id.type !== "Identifier" ||
    isPresent(object.id.typeAnnotation) ||
    object.init?.type !== "ObjectExpression" ||
    object.init.properties.length !== 1
  )
    return null;
  const property = object.init.properties[0];
  if (property?.type !== "Property" || property.computed || property.kind !== "init" || property.method ||
    property.value !== node) return null;
  const key = getPropertyName(property);
  if (key === null || key === "__proto__" || !soleLiteralRequest(sourceCode, returned.argument, declaration, object, key))
    return null;
  const replacement = property.shorthand
    ? `${sourceCode.getText(property.key)}: fetch.bind(undefined)`
    : "fetch.bind(undefined)";
  return (fixer) => fixer.replaceText(property.shorthand ? property : node, replacement);
}

function isShadowed(sourceCode: SourceCode, node: Node, name: string): boolean {
  return (findVariable(sourceCode.getScope(node), name)?.defs.length ?? 0) !== 0;
}

function soleLiteralRequest(
  sourceCode: SourceCode,
  node: Node | null | undefined,
  declaration: ESTree.VariableDeclaration,
  object: ESTree.VariableDeclarator,
  key: string,
): boolean {
  if (
    node?.type !== "CallExpression" ||
    node.optional ||
    isPresent(node.typeArguments) ||
    node.arguments.length !== 1 ||
    node.callee.type !== "MemberExpression" ||
    node.callee.optional ||
    getPropertyName(node.callee) !== key ||
    node.callee.object.type !== "Identifier" ||
    object.id.type !== "Identifier" ||
    node.callee.object.name !== object.id.name
  )
    return false;
  const input = node.arguments[0];
  if (input?.type !== "Literal" || typeof input.value !== "string" || !input.value.startsWith("data:"))
    return false;
  const identifier = object.id;
  const receiver = node.callee.object;
  const binding = sourceCode
    .getDeclaredVariables(declaration)
    .find((variable) => variable.name === identifier.name);
  return (
    binding !== undefined &&
    binding.defs.length === 1 &&
    binding.defs[0]?.node === object &&
    findVariable(sourceCode.getScope(receiver), identifier.name) === binding &&
    binding.references.every(
      (reference) => reference.identifier === identifier || reference.identifier === receiver,
    )
  );
}
