/**
 * @fileoverview _exported-next-config-property — resolve a known property of the effective exported Next configuration.
 */

import { ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

function unwrap(node: TSESTree.Node): TSESTree.Node {
  while (node.type === "TSAsExpression" || node.type === "TSSatisfiesExpression" || node.type === "TSTypeAssertion" || node.type === "TSNonNullExpression") node = node.expression;
  return node;
}

export function exportedNextConfigProperty(
  sourceCode: Readonly<TSESLint.SourceCode>,
  path: readonly string[],
): TSESTree.Property | null {
  const resolve = (input: TSESTree.Node, seen = new Set<TSESTree.Node>()): TSESTree.Node | null => {
    const node = unwrap(input);
    if (node.type !== "Identifier") return node;
    if (seen.has(node)) return null;
    seen.add(node);
    const binding = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
    const definition = binding?.defs.length === 1 ? binding.defs[0] : undefined;
    if (definition?.type !== "Variable" || definition.parent.kind !== "const" || definition.node.init === null ||
      binding?.references.some((reference) => reference.identifier !== node && reference.init !== true)) return null;
    return resolve(definition.node.init, seen);
  };
  let exported: TSESTree.Node | null = null;
  for (const statement of sourceCode.ast.body) {
    if (statement.type === "ExportDefaultDeclaration") exported = statement.declaration;
    if (statement.type !== "ExpressionStatement" || statement.expression.type !== "AssignmentExpression" || statement.expression.operator !== "=" || sourceCode.ast.body.length !== 1) continue;
    const assignment = statement.expression;
    const left = assignment.left;
    if (left.type !== "MemberExpression" || left.computed || left.object.type !== "Identifier" || left.object.name !== "module" || left.property.type !== "Identifier" || left.property.name !== "exports") continue;
    const binding = ASTUtils.findVariable(sourceCode.getScope(left.object), "module");
    if (binding === null || binding.defs.length === 0) exported = assignment.right;
  }
  if (exported === null) return null;
  let current: TSESTree.Node | null = resolve(exported);
  let selected: TSESTree.Property | null = null;
  for (const name of path) {
    if (current?.type !== "ObjectExpression" || current.properties.some((property) => property.type !== "Property" || property.computed || property.kind !== "init")) return null;
    selected = null;
    for (const property of current.properties) {
      if (property.type !== "Property") continue;
      const key = property.key.type === "Identifier" ? property.key.name : property.key.type === "Literal" ? property.key.value : null;
      if (key === name) selected = property;
    }
    if (selected === null) return null;
    current = resolve(selected.value);
  }
  return selected;
}
