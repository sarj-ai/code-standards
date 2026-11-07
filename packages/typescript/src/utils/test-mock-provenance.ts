/**
 * @fileoverview test-mock-provenance — resolve runtime test-framework bindings without trusting local names.
 *
 * The imported-local-names cache is keyed by the Program node, which Oxlint
 * creates fresh for every file; the fixture-API cache is keyed by scope variables.
 */

import type { ESTree, Identifier, Node, SourceCode, TsVariable } from "../types.js";
import { tsReference } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "./ast.js";
import { importSpecifierName } from "./import-specifier-name.js";
import { isConstDeclaration } from "./stable-value-binding.js";
import { findVariable, getPropertyName } from "./static-string.js";

export type { Identifier };

export type TestFrameworkKind = "test" | "assertion";

type ImportBindingSpecifier = ESTree.ImportSpecifier | ESTree.ImportDefaultSpecifier | ESTree.ImportNamespaceSpecifier;

export function importedTestMockNamespace(
  source: SourceCode,
  identifier: Identifier,
): "vitest" | "jest" | null {
  const binding = findVariable(source.getScope(identifier), identifier.name);
  const importedBinding = runtimeImportBinding(binding);
  if (importedBinding === null || importedBinding.specifier.type !== "ImportSpecifier") return null;
  const imported = importSpecifierName(importedBinding.specifier);
  const module = importedBinding.module;
  if (module === "vitest" && (imported === "vi" || imported === "vitest")) return "vitest";
  if (module === "@jest/globals" && imported === "jest") return "jest";
  return null;
}

export function isUnshadowedTestMockGlobal(source: SourceCode, identifier: Identifier): boolean {
  if (identifier.name !== "vi" && identifier.name !== "jest") return false;
  const binding = findVariable(source.getScope(identifier), identifier.name);
  return binding === null || (binding.defs.length === 0 && !binding.references.some((reference) => reference.isWrite()));
}

const TEST_FRAMEWORK_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);

/**
 * `runtimeTestFrameworkName` limited to `accepted` names. An identifier that is neither an accepted
 * name nor an import can only resolve to its own name or null, so it skips the scope lookup.
 */
export function acceptedTestFrameworkName(
  source: Readonly<SourceCode>,
  identifier: Identifier,
  kind: TestFrameworkKind,
  accepted: ReadonlySet<string>,
): string | null {
  if (!accepted.has(identifier.name) && !importedLocalNames(source.ast).has(identifier.name)) return null;
  const name = runtimeTestFrameworkName(source, identifier, kind);
  return name !== null && accepted.has(name) ? name : null;
}

export const EXPECT_ASSERTION: ReadonlySet<string> = new Set(["expect"]);

const IMPORTED_LOCAL_NAMES_BY_PROGRAM = new WeakMap<ESTree.Program, ReadonlySet<string>>();

/** Local names bound by the Program's top-level imports, cached per Program. */
function importedLocalNames(program: ESTree.Program): ReadonlySet<string> {
  let names = IMPORTED_LOCAL_NAMES_BY_PROGRAM.get(program);
  if (names === undefined) {
    names = new Set(program.body.flatMap((statement) =>
      statement.type === "ImportDeclaration" ? statement.specifiers.map((specifier) => specifier.local.name) : []));
    IMPORTED_LOCAL_NAMES_BY_PROGRAM.set(program, names);
  }
  return names;
}

/** Runtime binding provenance; caller-specific APIs and modifiers remain with their rule. */
export function runtimeTestFrameworkName(
  source: Readonly<SourceCode>,
  identifier: Identifier,
  kind: TestFrameworkKind,
): string | null {
  const binding = findVariable(source.getScope(identifier), identifier.name);
  if (binding === null || binding.defs.length === 0) {
    return binding?.references.some((reference) => reference.isWrite()) ? null : identifier.name;
  }
  const importedBinding = runtimeImportBinding(binding);
  if (importedBinding === null) return null;
  const { specifier, module } = importedBinding;
  const isNodeAssertion = kind === "assertion" && (module === "node:assert" || module === "node:assert/strict");
  if (specifier.type === "ImportSpecifier") {
    if (isNodeAssertion) return "assert";
    if (!TEST_FRAMEWORK_MODULES.has(module)) return null;
    return importSpecifierName(specifier);
  }
  if (isNodeAssertion) return "assert";
  return kind === "test" && module === "node:test" && specifier.type === "ImportDefaultSpecifier" ? "test" : null;
}

function runtimeImportBinding(
  binding: TsVariable | null,
): { readonly module: string; readonly specifier: ImportBindingSpecifier } | null {
  if (binding?.defs.length !== 1) return null;
  const definition = binding.defs[0];
  const declaration = definition?.parent;
  if (definition?.type !== "ImportBinding" || declaration?.type !== "ImportDeclaration" ||
    declaration.importKind === "type") return null;
  const specifier = definition.node;
  if (specifier.type !== "ImportSpecifier" && specifier.type !== "ImportDefaultSpecifier" &&
    specifier.type !== "ImportNamespaceSpecifier") return null;
  if (specifier.type === "ImportSpecifier" && specifier.importKind === "type") return null;
  return { module: declaration.source.value, specifier };
}

/** Follow only an unchanged local fixture API back to the canonical Vitest import. */
export function vitestFixtureTestName(
  source: Readonly<SourceCode>,
  identifier: Identifier,
): "it" | "test" | null {
  return fixtureTestName(identifier, source, new Set());
}

function fixtureTestName(
  node: Node,
  source: Readonly<SourceCode>,
  seen: Set<TsVariable>,
): "it" | "test" | null {
  node = unwrapExpression(node);
  if (node.type === "CallExpression") {
    const callee = unwrapExpression(node.callee);
    return !node.optional && callee.type === "MemberExpression" && !callee.optional &&
      getPropertyName(callee) === "extend" && node.arguments.length > 0 &&
      !node.arguments.some((argument) => argument.type === "SpreadElement")
      ? fixtureTestName(callee.object, source, seen) : null;
  }
  if (node.type !== "Identifier") return null;
  const binding = findVariable(source.getScope(node), node.name);
  if (binding === null || seen.has(binding) || !unchangedFixtureApi(binding)) return null;
  seen.add(binding);
  const imported = runtimeImportBinding(binding);
  if (imported?.module === "vitest" && imported.specifier.type === "ImportSpecifier") {
    const value = importSpecifierName(imported.specifier);
    return value === "test" || value === "it" ? value : null;
  }
  const definition = binding.defs[0];
  const declarator = definition?.node;
  if (binding.defs.length !== 1 || declarator?.type !== "VariableDeclarator" ||
      declarator.id.type !== "Identifier" || !isConstDeclaration(parentOf(declarator)) ||
      declarator.init === null || declarator.init.range[1] > node.range[0]) return null;
  const initializer = unwrapExpression(declarator.init);
  return initializer.type === "CallExpression" ? fixtureTestName(initializer, source, seen) : null;
}

const FIXTURE_API_STABILITY = new WeakMap<TsVariable, boolean>();

function unchangedFixtureApi(binding: TsVariable): boolean {
  const cached = FIXTURE_API_STABILITY.get(binding);
  if (cached !== undefined) return cached;
  const unchanged = binding.references.every((item) => {
    const reference = tsReference(item);
    if (reference.isWrite()) return reference.init === true;
    if (reference.isTypeReference && !reference.isValueReference) return true;
    let use = outerExpression(reference.identifier);
    let parent = parentOf(use);
    while (parent?.type === "MemberExpression" && parent.object === use) {
      use = outerExpression(parent);
      parent = parentOf(use);
    }
    return parent?.type === "CallExpression" && parent.callee === use ||
      parent?.type === "ExportSpecifier" || parent?.type === "ExportDefaultDeclaration" ||
      parent?.type === "TSTypeQuery" ||
      parent?.type === "UnaryExpression" && parent.operator === "typeof";
  });
  FIXTURE_API_STABILITY.set(binding, unchanged);
  return unchanged;
}
