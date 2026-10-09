/**
 * @fileoverview _test-mock-provenance — resolve runtime test-framework bindings without trusting local names.
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

export function importedTestMockNamespace(
  source: TSESLint.SourceCode,
  identifier: TSESTree.Identifier,
): "vitest" | "jest" | null {
  const binding = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  if (binding?.defs.length !== 1) return null;
  const definition = binding.defs[0];
  if (definition?.type !== "ImportBinding" || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || definition.parent.importKind === "type") return null;
  const specifier = definition.node;
  if (specifier.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type") return null;
  const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
  const module = definition.parent.source.value;
  if (module === "vitest" && (imported === "vi" || imported === "vitest")) return "vitest";
  if (module === "@jest/globals" && imported === "jest") return "jest";
  return null;
}

export function isUnshadowedTestMockGlobal(source: TSESLint.SourceCode, identifier: TSESTree.Identifier): boolean {
  if (identifier.name !== "vi" && identifier.name !== "jest") return false;
  const binding = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  return binding === null || (binding.defs.length === 0 && !binding.references.some((reference) => reference.isWrite()));
}
