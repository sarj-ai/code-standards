/**
 * @fileoverview _test-mock-provenance — resolve runtime test-framework bindings without trusting local names.
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

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

/** Follow only an unchanged local fixture API back to the canonical Vitest import. */
export function vitestFixtureTestName(
  source: Readonly<TSESLint.SourceCode>,
  identifier: TSESTree.Identifier,
): "it" | "test" | null {
  return fixtureTestName(identifier, source, new Set());
}

function fixtureTestName(
  node: TSESTree.Node,
  source: Readonly<TSESLint.SourceCode>,
  seen: Set<TSESLint.Scope.Variable>,
): "it" | "test" | null {
  node = unwrapExpression(node);
  if (node.type === AST_NODE_TYPES.CallExpression) {
    const callee = unwrapExpression(node.callee);
    return !node.optional && callee.type === AST_NODE_TYPES.MemberExpression && !callee.optional &&
      ASTUtils.getPropertyName(callee) === "extend" && node.arguments.length > 0 &&
      !node.arguments.some(argument => argument.type === AST_NODE_TYPES.SpreadElement)
      ? fixtureTestName(callee.object, source, seen) : null;
  }
  if (node.type !== AST_NODE_TYPES.Identifier) return null;
  const binding = ASTUtils.findVariable(source.getScope(node), node.name);
  if (binding === null || seen.has(binding) || !unchangedFixtureApi(binding)) return null;
  seen.add(binding);
  const imported = runtimeImportBinding(binding);
  if (imported?.module === "vitest" && imported.specifier.type === AST_NODE_TYPES.ImportSpecifier) {
    const name = imported.specifier.imported;
    const value = name.type === AST_NODE_TYPES.Identifier ? name.name : name.value;
    return value === "test" || value === "it" ? value : null;
  }
  const definition = binding.defs[0];
  if (binding.defs.length !== 1 || definition?.node.type !== AST_NODE_TYPES.VariableDeclarator ||
      definition.node.id.type !== AST_NODE_TYPES.Identifier || definition.node.parent.kind !== "const" ||
      definition.node.init === null || definition.node.init.range[1] > node.range[0]) return null;
  const initializer = unwrapExpression(definition.node.init);
  return initializer.type === AST_NODE_TYPES.CallExpression ? fixtureTestName(initializer, source, seen) : null;
}

const FIXTURE_API_STABILITY = new WeakMap<TSESLint.Scope.Variable, boolean>();

function unchangedFixtureApi(binding: TSESLint.Scope.Variable): boolean {
  const cached = FIXTURE_API_STABILITY.get(binding);
  if (cached !== undefined) return cached;
  const unchanged = binding.references.every(reference => {
    if (reference.isWrite()) return reference.init === true;
    if (reference.isTypeReference && !reference.isValueReference) return true;
    let use = outerExpression(reference.identifier);
    while (use.parent?.type === AST_NODE_TYPES.MemberExpression && use.parent.object === use) use = outerExpression(use.parent);
    const parent = use.parent;
    return parent?.type === AST_NODE_TYPES.CallExpression && parent.callee === use ||
      parent?.type === AST_NODE_TYPES.ExportSpecifier || parent?.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
      parent?.type === AST_NODE_TYPES.TSTypeQuery ||
      parent?.type === AST_NODE_TYPES.UnaryExpression && parent.operator === "typeof";
  });
  FIXTURE_API_STABILITY.set(binding, unchanged);
  return unchanged;
}
