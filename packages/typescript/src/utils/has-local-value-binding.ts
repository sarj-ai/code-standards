/** @fileoverview has-local-value-binding — preserve runtime bindings across erased type declarations. */

import type { ESTree, Node, Scope, SourceCode } from "../types.js";

/** Imports and unknown namespace bodies remain conservative value declarations. */
export function hasLocalValueBinding(
  source: Readonly<SourceCode>,
  identifier: ESTree.IdentifierReference | ESTree.BindingIdentifier | ESTree.IdentifierName,
  sourceType: ESTree.ModuleKind = source.ast.sourceType,
): boolean {
  // Some parsers flatten the CommonJS wrapper when building their scope tree.
  if (identifier.name === "arguments" && sourceType === "commonjs") return true;
  let scope: Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    // Ordinary functions own arguments even when there is no declaration node.
    if (variable !== undefined && identifier.name === "arguments" &&
      scope.type === "function" && scope.block.type !== "ArrowFunctionExpression") return true;
    // Parameter initializers cannot see declarations belonging to the body.
    const bodyStart = scope.type === "function" && scope.block.type !== "Program"
      ? functionBody(scope.block)?.range[0] : undefined;
    if (variable?.defs.some(definition =>
      (bodyStart === undefined || identifier.range[0] >= bodyStart || definition.name.range[0] < bodyStart) &&
      // TS-ESLint scope definitions carry "Type" and "TSModuleName", which Oxlint's typings omit.
      (definition.type as string) !== "Type" &&
      ((definition.type as string) !== "TSModuleName" ||
        !isTypeOnlyNamespace(definition.node as ESTree.TSModuleDeclaration)))) return true;
    scope = scope.upper;
  }
  return false;
}

/** A function scope's block body; Oxlint passes null where TS-ESTree omits it. */
function functionBody(block: Node): Node | null | undefined {
  return (block as { body?: Node | null }).body;
}

/** These namespace members are erased independently of const-enum compiler options. */
function isTypeOnlyNamespace(declaration: ESTree.TSModuleDeclaration): boolean {
  const pending = [declaration];
  while (pending.length > 0) {
    const current = pending.pop();
    // Oxlint gives a body-less `declare module "x";` a null body, TS-ESTree omits it.
    if (current?.body === undefined || current.body === null) return false;
    for (const statement of current.body.body) {
      const inner = statement.type === "ExportNamedDeclaration" ? statement.declaration : statement;
      if (inner === null || inner === undefined) return false;
      if (inner.type === "TSInterfaceDeclaration" || inner.type === "TSTypeAliasDeclaration") continue;
      if (inner.type !== "TSModuleDeclaration") return false;
      pending.push(inner as ESTree.TSModuleDeclaration);
    }
  }
  return true;
}
