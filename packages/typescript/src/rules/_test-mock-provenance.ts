/**
 * @fileoverview _test-mock-provenance — resolve runtime test-framework bindings without trusting local names.
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

export function importedTestMockNamespace(
  source: TSESLint.SourceCode,
  identifier: TSESTree.Identifier,
): "vitest" | "jest" | null {
  const binding = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  const importedBinding = runtimeImportBinding(binding);
  if (importedBinding === null || importedBinding.specifier.type !== AST_NODE_TYPES.ImportSpecifier) return null;
  const specifier = importedBinding.specifier;
  const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
  const module = importedBinding.module;
  if (module === "vitest" && (imported === "vi" || imported === "vitest")) return "vitest";
  if (module === "@jest/globals" && imported === "jest") return "jest";
  return null;
}

export function isUnshadowedTestMockGlobal(source: TSESLint.SourceCode, identifier: TSESTree.Identifier): boolean {
  if (identifier.name !== "vi" && identifier.name !== "jest") return false;
  const binding = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  return binding === null || (binding.defs.length === 0 && !binding.references.some((reference) => reference.isWrite()));
}


const TEST_FRAMEWORK_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);

/** Runtime binding provenance; caller-specific APIs and modifiers remain with their rule. */
export function runtimeTestFrameworkName(
  source: Readonly<TSESLint.SourceCode>,
  identifier: TSESTree.Identifier,
  kind: "test" | "assertion",
): string | null {
  const binding = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  if (binding === null || binding.defs.length === 0) {
    return binding?.references.some(reference => reference.isWrite()) ? null : identifier.name;
  }
  const importedBinding = runtimeImportBinding(binding);
  if (importedBinding === null) return null;
  const { specifier, module } = importedBinding;
  const isNodeAssertion = kind === "assertion" && (module === "node:assert" || module === "node:assert/strict");
  if (specifier.type === AST_NODE_TYPES.ImportSpecifier) {
    if (isNodeAssertion) return "assert";
    if (!TEST_FRAMEWORK_MODULES.has(module)) return null;
    const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
    return imported;
  }
  if (isNodeAssertion) return "assert";
  return kind === "test" && module === "node:test" && specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ? "test" : null;
}


function runtimeImportBinding(
  binding: TSESLint.Scope.Variable | null,
): { readonly module: string; readonly specifier: TSESTree.ImportSpecifier | TSESTree.ImportDefaultSpecifier | TSESTree.ImportNamespaceSpecifier } | null {
  if (binding?.defs.length !== 1) return null;
  const definition = binding.defs[0];
  if (definition?.type !== "ImportBinding" || definition.parent.type !== AST_NODE_TYPES.ImportDeclaration || definition.parent.importKind === "type") return null;
  const specifier = definition.node;
  if (specifier.type !== AST_NODE_TYPES.ImportSpecifier && specifier.type !== AST_NODE_TYPES.ImportDefaultSpecifier && specifier.type !== AST_NODE_TYPES.ImportNamespaceSpecifier) return null;
  if (specifier.type === AST_NODE_TYPES.ImportSpecifier && specifier.importKind === "type") return null;
  return { module: definition.parent.source.value, specifier };
}
