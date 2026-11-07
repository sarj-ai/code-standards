/**
 * @fileoverview native-fetch-reference — prove bounded native fetch references without evaluating wrappers.
 */

import type { ESTree, Node, SourceCode, TsVariable } from "../types.js";
import { unwrapExpression } from "./ast.js";
import { nativeRuntimeUnchanged } from "./native-runtime-unchanged.js";
import { findVariable, staticPropertyName } from "./static-string.js";

const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "self", "window"]);

/** Follow only unshadowed native references and stable const aliases without defaults. */
export function nativeFetchReference(
  node: Node,
  sourceCode: Readonly<SourceCode>,
): boolean {
  return lexicalFetchReference(node, sourceCode) && nativeRuntimeUnchanged(sourceCode, "fetch");
}

function lexicalFetchReference(
  node: Node,
  sourceCode: Readonly<SourceCode>,
  seen = new Set<TsVariable>(),
): boolean {
  const expression = unwrapExpression(node);
  if (expression.type === "MemberExpression") {
    return staticPropertyName(expression, sourceCode) === "fetch" && globalReceiver(expression.object, sourceCode);
  }
  if (expression.type !== "Identifier") return false;
  const binding = findVariable(sourceCode.getScope(expression), expression.name);
  if (binding === null || binding.defs.length === 0) return expression.name === "fetch";
  if (seen.has(binding) || seen.size >= 8 || binding.defs.length !== 1 ||
    binding.references.some(reference => reference.isWrite() && reference.init !== true)) return false;
  seen.add(binding);
  const [definition] = binding.defs;
  if (definition?.type !== "Variable" || (definition.parent as ESTree.VariableDeclaration).kind !== "const") return false;
  const declarator = definition.node as ESTree.VariableDeclarator;
  if (declarator.init === null) return false;
  if (declarator.id.type === "Identifier") {
    return lexicalFetchReference(declarator.init, sourceCode, seen);
  }
  return declarator.id.type === "ObjectPattern" && globalReceiver(declarator.init, sourceCode) &&
    declarator.id.properties.some(property => property.type === "Property" &&
      staticPropertyName(property as ESTree.ObjectProperty, sourceCode) === "fetch" && property.value.type === "Identifier" &&
      findVariable(sourceCode.getScope(property.value), property.value.name) === binding);
}

function globalReceiver(node: Node, sourceCode: Readonly<SourceCode>): boolean {
  const receiver = unwrapExpression(node);
  return receiver.type === "Identifier" && GLOBAL_RECEIVERS.has(receiver.name) &&
    !findVariable(sourceCode.getScope(receiver), receiver.name)?.defs.length;
}
