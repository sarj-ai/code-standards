/**
 * @fileoverview exported-next-config-property — resolve a known property of the effective exported Next configuration.
 *
 * Port of the 18.x `_exported-next-config-property.ts` helper. The type-contract walk
 * in `canAutofixNextConfigLiteral` skips Oxlint's `Program.tokens` and
 * `Program.comments`: no token or comment has a `typeAnnotation` key or a
 * TS-assertion type, so the result is unchanged and the walk avoids
 * materializing tokens.
 */

import type { ESTree, Node, SourceCode } from "../types.js";
import { forEachOwnAstChild, unwrapExpression } from "./ast.js";
import { findVariable, getPropertyName } from "./static-string.js";

export function exportedNextConfigProperty(
  sourceCode: Readonly<SourceCode>,
  path: readonly string[],
): ESTree.ObjectProperty | null {
  const resolve = (input: Node, seen = new Set<Node>()): Node | null => {
    const node = unwrapExpression(input);
    if (node.type !== "Identifier") return node;
    if (seen.has(node)) return null;
    seen.add(node);
    const binding = findVariable(sourceCode.getScope(node), node.name);
    const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
    if (definition?.type !== "Variable") return null;
    const declaration = definition.parent as ESTree.VariableDeclaration | null;
    const declarator = definition.node as ESTree.VariableDeclarator;
    if (declaration?.kind !== "const" || declarator.init === null ||
      binding?.references.some((reference) => reference.identifier !== node && reference.init !== true)) return null;
    return resolve(declarator.init, seen);
  };
  const exported = exportedConfig(sourceCode);
  if (exported === null) return null;
  let current: Node | null = resolve(exported);
  let selected: ESTree.ObjectProperty | null = null;
  for (const name of path) {
    if (current?.type !== "ObjectExpression" || current.properties.some((property) =>
      property.type !== "Property" || getPropertyName(property) === null || property.kind !== "init")) return null;
    selected = objectProperty(current, name);
    if (selected === null) return null;
    current = resolve(selected.value);
  }
  return selected;
}

function exportedConfig(sourceCode: Readonly<SourceCode>): Node | null {
  let exported: Node | null = null;
  for (const statement of sourceCode.ast.body) {
    if (statement.type === "ExportDefaultDeclaration") exported = statement.declaration;
    if (statement.type !== "ExpressionStatement" || statement.expression.type !== "AssignmentExpression" ||
      statement.expression.operator !== "=" || sourceCode.ast.body.length !== 1) continue;
    const assignment = statement.expression;
    const left = assignment.left;
    if (left.type !== "MemberExpression" || left.computed || left.object.type !== "Identifier" ||
      left.object.name !== "module" || left.property.type !== "Identifier" || left.property.name !== "exports") continue;
    const binding = findVariable(sourceCode.getScope(left.object), "module");
    if (binding === null || binding.defs.length === 0) exported = assignment.right;
  }
  return exported;
}

function objectProperty(node: ESTree.ObjectExpression, name: string): ESTree.ObjectProperty | null {
  let selected: ESTree.ObjectProperty | null = null;
  for (const property of node.properties) {
    if (property.type !== "Property") continue;
    const key = getPropertyName(property);
    if (key === name) selected = property;
  }
  return selected;
}

/** Explicit module contracts may require literal true even after an alias is resolved. */
export function canAutofixNextConfigLiteral(sourceCode: Readonly<SourceCode>): boolean {
  const constrained = (node: Node): boolean => {
    if (node.type === "TSAsExpression") {
      if (!(node.typeAnnotation.type === "TSTypeReference" && node.typeAnnotation.typeName.type === "Identifier" &&
        node.typeAnnotation.typeName.name === "const")) return true;
      return constrained(node.expression);
    }
    if (("typeAnnotation" in node && node.typeAnnotation !== undefined && node.typeAnnotation !== null) ||
      // Oxlint's `Node` union omits these two types although its parser emits them.
      (node.type as string) === "TSSatisfiesExpression" || (node.type as string) === "TSTypeAssertion") return true;
    return forEachOwnAstChild(node, constrained, (key) => key !== "tokens" && key !== "comments");
  };
  return !constrained(sourceCode.ast) &&
    !sourceCode.getAllComments().some((comment) => /@(?:type|satisfies|enum)\b/u.test(comment.value));
}
