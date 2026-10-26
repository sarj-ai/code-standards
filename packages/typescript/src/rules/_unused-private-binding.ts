/**
 * @fileoverview _unused-private-binding — prove a private declaration has no observable source references.
 */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { retainsNamedTypeUses } from "./_type-binding.js";
import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";

/** Dynamic eval and script globals prevent a file-local non-observation proof. */
export function isUnusedPrivateBinding(
  sourceCode: Readonly<TSESLint.SourceCode>,
  declaration: TSESTree.VariableDeclarator | TSESTree.ClassDeclaration | TSESTree.TSInterfaceDeclaration | TSESTree.TSTypeAliasDeclaration | TSESTree.TSEnumDeclaration | TSESTree.FunctionDeclaration,
  identifier: TSESTree.Identifier,
  filename: string,
  allowedDeclarations: readonly TSESTree.Node[] = [declaration],
): boolean {
  if (/\.d\.[cm]?ts$/u.test(filename)) return false;
  const bindings = sourceCode.getDeclaredVariables(declaration).filter((binding) => binding.name === identifier.name);
  if (bindings.length === 0 || bindings.some((binding) => binding.defs.length !== allowedDeclarations.length || binding.defs.some((definition) => !allowedDeclarations.includes(definition.node)) || binding.eslintUsed ||
    binding.references.some((reference) => reference.isRead() || reference.init !== true))) return false;
  if (hasIdentifierNamed(sourceCode.ast, "eval")) return false;
  const statement = declaration.type === AST_NODE_TYPES.VariableDeclarator ? declaration.parent : declaration;
  if (statement.parent.type === AST_NODE_TYPES.ExportNamedDeclaration || statement.parent.type === AST_NODE_TYPES.ExportDefaultDeclaration) return false;
  if (statement.parent.type !== AST_NODE_TYPES.Program) return statement.parent.type === AST_NODE_TYPES.BlockStatement;
  return sourceCode.ast.body.some((node) => node.type === AST_NODE_TYPES.ImportDeclaration ||
    node.type === AST_NODE_TYPES.ExportNamedDeclaration || node.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
    node.type === AST_NODE_TYPES.ExportAllDeclaration);
}

/** Imported factories/namespaces must not be assigned, aliased, or passed outward. */
export function hasOnlyDirectFactoryUses(variable: TSESLint.Scope.Variable): boolean {
  return variable.references.every((reference) => {
    if (reference.isTypeReference && !reference.isValueReference) return true;
    const identifier = reference.identifier;
    const parent = identifier.parent;
    if (parent.type === AST_NODE_TYPES.CallExpression && parent.callee === identifier) return true;
    return parent.type === AST_NODE_TYPES.MemberExpression && parent.object === identifier &&
      !parent.computed && parent.parent.type === AST_NODE_TYPES.CallExpression && parent.parent.callee === parent;
  });
}

const IDENTIFIER_NAMES = new WeakMap<TSESTree.Node, ReadonlySet<string>>();

/** Cache identifier identity once per immutable AST without recursive tree walking. */
export function hasIdentifierNamed(node: TSESTree.Node, name: string): boolean {
  let names = IDENTIFIER_NAMES.get(node);
  if (names === undefined) {
    const collected = new Set<string>();
    const pending = [node];
    const seen = new WeakSet<TSESTree.Node>();
    while (pending.length > 0) {
      const current = pending.pop();
      if (current === undefined || seen.has(current)) continue;
      seen.add(current);
      if (current.type === AST_NODE_TYPES.Identifier || current.type === AST_NODE_TYPES.JSXIdentifier) collected.add(current.name);
      forEachOwnAstChild(current, (child) => { pending.push(child); }, (key) => key !== "tokens" && key !== "comments");
    }
    names = collected;
    IDENTIFIER_NAMES.set(node, names);
  }
  return names.has(name);
}

/** Remove an unobserved private function's unsound narrowing contract, retaining its runtime check. */
export function privatePredicateBooleanFix(
  sourceCode: Readonly<TSESLint.SourceCode>,
  node: TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression,
  annotation: TSESTree.TSTypePredicate,
  filename: string,
): TSESLint.ReportFixFunction | null {
  if (!annotation.typeAnnotation || !retainsNamedTypeUses(sourceCode, annotation.typeAnnotation) ||
    node.type !== AST_NODE_TYPES.FunctionDeclaration || node.id === null ||
    !isUnusedPrivateBinding(sourceCode, node, node.id, filename) || sourceCode.getCommentsInside(annotation).length > 0) return null;
  return (fixer) => fixer.replaceText(annotation, `boolean${sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")}`);
}
