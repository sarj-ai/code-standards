/** @fileoverview _has-local-value-binding — preserve runtime bindings across erased type declarations. */

import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";
import type { Linter } from "eslint";

import type { TypeScriptSourceCode } from "./_eslint-rule.js";

/** Imports and unknown namespace bodies remain conservative value declarations. */
export function hasLocalValueBinding(
  source: Readonly<TypeScriptSourceCode>,
  identifier: TSESTree.Identifier,
  sourceType: Linter.SourceType = source.ast.sourceType,
): boolean {
  // Some parsers flatten the CommonJS wrapper when building their scope tree.
  if (identifier.name === "arguments" && sourceType === "commonjs") return true;
  let scope: TSESLint.Scope.Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    // Ordinary functions own arguments even when there is no declaration node.
    if (variable !== undefined && identifier.name === "arguments" &&
      scope.type === "function" && scope.block.type !== AST_NODE_TYPES.ArrowFunctionExpression) return true;
    // Parameter initializers cannot see declarations belonging to the body.
    const bodyStart = scope.type === "function" && scope.block.type !== AST_NODE_TYPES.Program
      ? scope.block.body?.range[0] : undefined;
    if (variable?.defs.some(definition =>
      (bodyStart === undefined || identifier.range[0] >= bodyStart || definition.name.range[0] < bodyStart) &&
      definition.type !== "Type" &&
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
