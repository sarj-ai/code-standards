/** @fileoverview _has-local-value-binding — preserve runtime bindings across erased type declarations. */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import type { TypeScriptSourceCode } from "./_eslint-rule.js";

/** Imports and unknown namespace bodies remain conservative value declarations. */
export function hasLocalValueBinding(
  source: Readonly<TypeScriptSourceCode>,
  identifier: TSESTree.Identifier,
): boolean {
  let scope: TSESLint.Scope.Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    if (variable?.defs.some(definition => definition.type !== "Type" &&
      (definition.type !== "TSModuleName" || !isTypeOnlyNamespace(definition.node)))) return true;
    scope = scope.upper;
  }
  return false;
}

/** These namespace members are erased independently of const-enum compiler options. */
function isTypeOnlyNamespace(declaration: TSESTree.TSModuleDeclaration): boolean {
  const pending = [declaration];
  while (pending.length > 0) {
    const current = pending.pop();
    if (current?.body === undefined) return false;
    for (const statement of current.body.body) {
      const inner = statement.type === AST_NODE_TYPES.ExportNamedDeclaration ? statement.declaration : statement;
      if (inner === null) return false;
      if (inner.type === AST_NODE_TYPES.TSInterfaceDeclaration || inner.type === AST_NODE_TYPES.TSTypeAliasDeclaration) continue;
      if (inner.type !== AST_NODE_TYPES.TSModuleDeclaration) return false;
      pending.push(inner);
    }
  }
  return true;
}
