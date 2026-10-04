/**
 * @fileoverview _exported-next-config-property — resolve a known property of the effective exported Next configuration.
 */

import type { ESTree, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


function unwrap(node: ESTree.Node): ESTree.Node {
  while (node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression" || node.type === "TSTypeAssertion" || node.type === "TSNonNullExpression") node = node.expression;
  return node;
}

export function exportedNextConfigProperty(
  sourceCode: Readonly<SourceCode>,
  path: readonly string[],
): ESTree.ObjectProperty | null {
  const resolve = (input: ESTree.Node, seen = new Set<ESTree.Node>()): ESTree.Node | null => {
    const node = unwrap(input);
    if (node.type !== "Identifier") return node;
    if (seen.has(node)) return null;
    seen.add(node);
    const binding = findVariable(sourceCode.getScope(node), node.name);
    const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
    if (definition?.type !== "Variable" || definition.node.type !== "VariableDeclarator" || definition.parent?.type !== "VariableDeclaration" || definition.parent.kind !== "const" || definition.node.init === null ||
      binding?.references.some((reference) => reference.identifier !== node && reference.init !== true)) return null;
    return resolve(definition.node.init, seen);
  };
  const exported = exportedConfig(sourceCode);
  if (exported === null) return null;
  let current: ESTree.Node | null = resolve(exported);
  let selected: ESTree.ObjectProperty | null = null;
  for (const name of path) {
    if (current?.type !== "ObjectExpression" || current.properties.some((property) => property.type !== "Property" || property.computed || property.kind !== "init")) return null;
    selected = objectProperty(current, name);
    if (selected === null) return null;
    current = resolve(selected.value);
  }
  return selected;
}

function exportedConfig(sourceCode: Readonly<SourceCode>): ESTree.Node | null {
  let exported: ESTree.Node | null = null;
  for (const statement of sourceCode.ast.body) {
    if (statement.type === "ExportDefaultDeclaration") exported = statement.declaration;
    if (statement.type !== "ExpressionStatement" || statement.expression.type !== "AssignmentExpression" || statement.expression.operator !== "=" || sourceCode.ast.body.length !== 1) continue;
    const assignment = statement.expression;
    const left = assignment.left;
    if (left.type !== "MemberExpression" || left.computed || left.object.type !== "Identifier" || left.object.name !== "module" || left.property.type !== "Identifier" || left.property.name !== "exports") continue;
    const binding = findVariable(sourceCode.getScope(left.object), "module");
    if (binding === null || binding.defs.length === 0) exported = assignment.right;
  }
  return exported;
}

function objectProperty(node: ESTree.ObjectExpression, name: string): ESTree.ObjectProperty | null {
  let selected: ESTree.ObjectProperty | null = null;
  for (const property of node.properties) {
    if (property.type !== "Property") continue;
    const key = property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? property.key.value : null;
    if (key === name) selected = property;
  }
  return selected;
}
