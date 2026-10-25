/** @fileoverview _type-binding — resolve type names without value-only shadowing. */
import { AST_NODE_TYPES, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

export function typeBinding(
  source: Readonly<TSESLint.SourceCode>,
  identifier: TSESTree.Identifier,
): TSESLint.Scope.Variable | null {
  let scope: TSESLint.Scope.Scope | null = source.getScope(identifier);
  while (scope !== null) {
    const variable = scope.set.get(identifier.name);
    if (variable !== undefined &&
      (variable.isTypeVariable || variable.defs.some(definition => definition.isTypeDefinition))) {
      return variable;
    }
    scope = scope.upper;
  }
  return null;
}

/** Erased named reads need an independent public type use that no SAFE fixer removes. */
export function retainsNamedTypeUses(
  source: Readonly<TSESLint.SourceCode>,
  removed: TSESTree.Node,
): boolean {
  const manager = source.scopeManager;
  if (manager === null) return false;
  const references = manager.scopes.flatMap((scope) => scope.references)
    .filter((reference) => reference.isRead() && insideTypeRange(reference.identifier, removed));
  return references.every((reference) => {
    const binding = reference.resolved;
    if (!binding || (!reference.isTypeReference && !reference.isValueReference)) return false;
    if (binding.defs.length === 0) return true;
    return binding.references.some((retained) => retained.isRead() &&
      (!reference.isTypeReference || retained.isTypeReference) &&
      (!reference.isValueReference || retained.isValueReference) &&
      !insideTypeRange(retained.identifier, removed) &&
      !binding.defs.some((definition) => insideTypeRange(retained.identifier, definition.node)) &&
      publicTypeUse(retained.identifier));
  });
}

/** Private declarations and erasable annotations cannot keep one another live. */
function publicTypeUse(identifier: TSESTree.Identifier | TSESTree.JSXIdentifier): boolean {
  let node: TSESTree.Node = identifier;
  while (node.parent) {
    if (node.type === AST_NODE_TYPES.TSTypeAnnotation || node.type === AST_NODE_TYPES.TSTypePredicate ||
      node.type === AST_NODE_TYPES.TSAsExpression || node.type === AST_NODE_TYPES.TSTypeAssertion) return false;
    if (node.type === AST_NODE_TYPES.TSTypeAliasDeclaration) {
      return node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration &&
        node.parent.declaration === node && node.parent.parent.type === AST_NODE_TYPES.Program;
    }
    if (node.type === AST_NODE_TYPES.ExportSpecifier) {
      return node.parent.type === AST_NODE_TYPES.ExportNamedDeclaration &&
        node.parent.source === null && node.parent.parent.type === AST_NODE_TYPES.Program;
    }
    node = node.parent;
  }
  return false;
}

function insideTypeRange(node: TSESTree.Node, range: TSESTree.Node): boolean {
  return node.range[0] >= range.range[0] && node.range[1] <= range.range[1];
}
