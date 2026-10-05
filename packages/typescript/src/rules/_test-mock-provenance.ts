/**
 * @fileoverview _test-mock-provenance — resolve runtime test-framework bindings without trusting local names.
 */

import type { ESTree, SourceCode } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


export function importedTestMockNamespace(
  source: SourceCode,
  identifier: ESTree.BindingIdentifier,
): "vitest" | "jest" | null {
  const binding = findVariable(source.getScope(identifier), identifier.name);
  if (binding?.defs.length !== 1) return null;
  const definition = binding.defs[0];
  if (definition?.type !== "ImportBinding" || definition.parent?.type !== "ImportDeclaration" || definition.parent.importKind === "type") return null;
  const specifier = definition.node;
  if (specifier.type !== "ImportSpecifier" || specifier.importKind === "type") return null;
  const imported = specifier.imported.type === "Identifier" ? specifier.imported.name : specifier.imported.value;
  const module = definition.parent.source.value;
  if (module === "vitest" && (imported === "vi" || imported === "vitest")) return "vitest";
  if (module === "@jest/globals" && imported === "jest") return "jest";
  return null;
}

export function isUnshadowedTestMockGlobal(source: SourceCode, identifier: ESTree.BindingIdentifier): boolean {
  if (identifier.name !== "vi" && identifier.name !== "jest") return false;
  const binding = findVariable(source.getScope(identifier), identifier.name);
  return binding === null || (binding.defs.length === 0 && !binding.references.some((reference) => reference.isWrite()));
}
