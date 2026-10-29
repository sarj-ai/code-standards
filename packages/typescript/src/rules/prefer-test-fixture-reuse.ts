/**
 * @fileoverview prefer-test-fixture-reuse — Reuse a requested test fixture instead of constructing another instance of its class.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-test-fixture-reuse.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { directArgumentCall, unwrapExpression } from "./_unwrap-expression.js";

type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression;
type FixtureConstructors = ReadonlyMap<string, TSESLint.Scope.Variable>;
interface FixtureExtension {
  readonly receiver: TSESTree.Expression;
  readonly declarations: TSESTree.ObjectExpression;
}
const MAX_DEPTH = 8;
const FRAMEWORKS: ReadonlySet<string> = new Set(["vitest", "@playwright/test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["only", "skip", "concurrent", "sequential"]);

export const PREFER_TEST_FIXTURE_REUSE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Reuse a requested test fixture instead of constructing another instance of its class.",
  rationale: "A second constructor bypasses the fixture's overrides, caching, configuration and cleanup ownership.",
  remediation: "Use the requested fixture. Supply a typed factory fixture when a test requires different configuration or multiple independent instances.",
  category: "testing",
  autofix: "none",
  limitations: [
    "Follows unchanged local const Vitest/Playwright test.extend APIs with literal fixture objects. A fixture must supply a source-resolved new-expression directly or through one local const to its use callback. Direct value fixtures are supported.",
    "Only constructors directly in a requesting test callback are compared by lexical binding identity. Renamed fixture parameters and stable constructor aliases are supported; nested callbacks, imported fixture APIs, dynamic factories, spread fixtures, mutable APIs and table-driven tests are excluded.",
    "Reports variants for review without replacing constructor arguments or changing lifecycle. Interface substitution across different concrete constructors requires typed project analysis and is not inferred.",
  ],
  examples: [
    { id: "duplicate-store", title: "The test constructs the store its fixture supplied", outcome: "match", files: [{ path: "src/store.test.ts", source: "import {test as base} from 'vitest'; class Store {} const test = base.extend({store: async ({}, use) => { await use(new Store()); }}); test('reads', ({store}) => { const other = new Store(); expect(other).toBeDefined(); });" }], focusPath: "src/store.test.ts", expectedCount: 1, public: true },
    { id: "reuse-store", title: "Request and use the store fixture", outcome: "no-match", files: [{ path: "src/store.test.ts", source: "import {test as base} from 'vitest'; class Store {} const test = base.extend({store: async ({}, use) => { await use(new Store()); }}); test('reads', ({store}) => { expect(store).toBeDefined(); });" }], focusPath: "src/store.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

function stableBinding(source: Readonly<TSESLint.SourceCode>, identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null {
  const variable = ASTUtils.findVariable(source.getScope(identifier), identifier.name);
  if (variable?.defs.length !== 1 || variable.references.some(reference => reference.isWrite() && !reference.init)) return null;
  return variable;
}

function constructorBinding(source: Readonly<TSESLint.SourceCode>, node: TSESTree.Node, depth = 0): TSESLint.Scope.Variable | null {
  node = unwrapExpression(node);
  if (node.type !== AST_NODE_TYPES.Identifier || depth >= MAX_DEPTH) return null;
  const variable = stableBinding(source, node);
  const definition = variable?.defs[0];
  if (variable === null || definition === undefined) return null;
  if (definition.type === "ClassName") return variable;
  if (definition.type === "ImportBinding" && definition.parent.type === AST_NODE_TYPES.ImportDeclaration && definition.parent.importKind !== "type" &&
      (definition.node.type !== AST_NODE_TYPES.ImportSpecifier || definition.node.importKind !== "type")) return variable;
  if (definition.node.type === AST_NODE_TYPES.VariableDeclarator && definition.node.parent.kind === "const" &&
      definition.node.init !== null && definition.node.range[1] < node.range[0]) return constructorBinding(source, definition.node.init, depth + 1);
  return null;
}

function fixtureApi(source: Readonly<TSESLint.SourceCode>, expression: TSESTree.Node, depth = 0): FixtureConstructors | null {
  const node = unwrapExpression(expression);
  if (node.type !== AST_NODE_TYPES.Identifier || depth >= MAX_DEPTH) return null;
  const variable = stableBinding(source, node);
  const definition = variable?.defs[0];
  if (variable === null || definition === undefined) return null;
  if (importedFixtureApi(variable)) return new Map();
  const extension = fixtureExtension(definition.node, node.range[0]);
  if (extension === null || !fixtureApiStable(variable)) return null;
  const inherited = fixtureApi(source, extension.receiver, depth + 1);
  return inherited === null ? null : fixtureConstructors(source, extension.declarations, inherited);
}

function importedFixtureApi(variable: TSESLint.Scope.Variable): boolean {
  const definition = variable.defs[0];
  if (definition?.type === "ImportBinding" && definition.parent.type === AST_NODE_TYPES.ImportDeclaration &&
      FRAMEWORKS.has(definition.parent.source.value) && definition.parent.importKind !== "type" &&
      definition.node.type === AST_NODE_TYPES.ImportSpecifier && definition.node.importKind !== "type") {
    const imported = definition.node.imported;
    const name = imported.type === AST_NODE_TYPES.Identifier ? imported.name : imported.value;
    return name === "test" || name === "it";
  }
  return false;
}

function fixtureExtension(declaration: TSESTree.Node, before: number): FixtureExtension | null {
  if (declaration.type !== AST_NODE_TYPES.VariableDeclarator || declaration.parent.kind !== "const" ||
      declaration.init === null || declaration.range[1] >= before) return null;
  const initial = unwrapExpression(declaration.init);
  if (initial.type !== AST_NODE_TYPES.CallExpression || initial.optional || initial.arguments.length !== 1 ||
      initial.callee.type !== AST_NODE_TYPES.MemberExpression || initial.callee.optional ||
      ASTUtils.getPropertyName(initial.callee) !== "extend") return null;
  const declarations = initial.arguments[0];
  if (declarations?.type !== AST_NODE_TYPES.ObjectExpression || declarations.properties.some(property => property.type !== AST_NODE_TYPES.Property || property.computed || property.kind !== "init")) return null;
  return { receiver: initial.callee.object, declarations };
}

function fixtureApiStable(variable: TSESLint.Scope.Variable): boolean {
  return !variable.references.some(reference => {
    if (reference.isWrite() || reference.isTypeReference && !reference.isValueReference) return false;
    let use: TSESTree.Node = reference.identifier;
    while (use.parent?.type === AST_NODE_TYPES.MemberExpression && use.parent.object === use) use = use.parent;
    return use.parent?.type !== AST_NODE_TYPES.CallExpression || use.parent.callee !== use;
  });
}

function fixtureConstructors(source: Readonly<TSESLint.SourceCode>, declarations: TSESTree.ObjectExpression, inherited: FixtureConstructors): FixtureConstructors {
  const result = new Map(inherited);
  for (const property of declarations.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.computed || property.value.type === AST_NODE_TYPES.AssignmentPattern) continue;
    const name = ASTUtils.getPropertyName(property);
    if (name === null || property.value.type === AST_NODE_TYPES.TSEmptyBodyFunctionExpression) continue;
    const constructor = fixtureConstructor(source, property.value);
    if (constructor === null) result.delete(name);
    else result.set(name, constructor);
  }
  return result;
}

function fixtureConstructor(source: Readonly<TSESLint.SourceCode>, value: TSESTree.Expression): TSESLint.Scope.Variable | null {
  value = unwrapExpression(value);
  if (value.type !== AST_NODE_TYPES.ArrowFunctionExpression && value.type !== AST_NODE_TYPES.FunctionExpression) return newConstructor(source, value);
  const use = value.params[1];
  if (use?.type !== AST_NODE_TYPES.Identifier) return null;
  const binding = stableBinding(source, use);
  const calls = scopeNodes(value.body, source).filter((node): node is TSESTree.CallExpression =>
    node.type === AST_NODE_TYPES.CallExpression && !node.optional && node.arguments.length === 1 &&
    node.callee.type === AST_NODE_TYPES.Identifier && stableBinding(source, node.callee) === binding);
  if (calls.length !== 1 || binding === null) return null;
  const argument = calls[0]?.arguments[0];
  return argument === undefined || argument.type === AST_NODE_TYPES.SpreadElement ? null : newConstructor(source, argument);
}

function newConstructor(source: Readonly<TSESLint.SourceCode>, expression: TSESTree.Node): TSESLint.Scope.Variable | null {
  const value = unwrapExpression(expression);
  if (value.type === AST_NODE_TYPES.NewExpression) return constructorBinding(source, value.callee);
  if (value.type !== AST_NODE_TYPES.Identifier) return null;
  const variable = stableBinding(source, value);
  const declaration = variable?.defs[0]?.node;
  if (declaration?.type !== AST_NODE_TYPES.VariableDeclarator || declaration.parent.kind !== "const" ||
      declaration.init === null || declaration.range[1] >= value.range[0]) return null;
  const initial = unwrapExpression(declaration.init);
  return initial.type === AST_NODE_TYPES.NewExpression ? constructorBinding(source, initial.callee) : null;
}

function scopeNodes(root: TSESTree.Node, source: Readonly<TSESLint.SourceCode>): TSESTree.Node[] {
  const result: TSESTree.Node[] = [];
  const pending = [root];
  while (pending.length > 0) {
    const node = pending.pop();
    if (node === undefined) continue;
    result.push(node);
    if (node !== root && (node.type === AST_NODE_TYPES.ArrowFunctionExpression || node.type === AST_NODE_TYPES.FunctionExpression ||
        node.type === AST_NODE_TYPES.FunctionDeclaration || node.type === AST_NODE_TYPES.ClassDeclaration || node.type === AST_NODE_TYPES.ClassExpression)) continue;
    for (const key of source.visitorKeys[node.type] ?? []) {
      const value: unknown = Reflect.get(node, key);
      if (Array.isArray(value)) pending.push(...value.filter(isNode));
      else if (isNode(value)) pending.push(value);
    }
  }
  return result;
}

function isNode(value: unknown): value is TSESTree.Node {
  return typeof value === "object" && value !== null && "type" in value && typeof value.type === "string";
}

function testApiCallee(expression: TSESTree.Node): TSESTree.Node {
  let node = unwrapExpression(expression);
  while (node.type === AST_NODE_TYPES.MemberExpression && !node.optional && TEST_MODIFIERS.has(ASTUtils.getPropertyName(node) ?? "")) node = unwrapExpression(node.object);
  return node;
}

function requestingFunction(node: TSESTree.Node): FunctionNode | null {
  for (let current = node.parent; current != null; current = current.parent) {
    if (current.type === AST_NODE_TYPES.ArrowFunctionExpression || current.type === AST_NODE_TYPES.FunctionExpression) return current;
    if (current.type === AST_NODE_TYPES.FunctionDeclaration) return null;
  }
  return null;
}

export default createRule<[], "reuseFixture">({
  name: "prefer-test-fixture-reuse",
  documentation: PREFER_TEST_FIXTURE_REUSE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_TEST_FIXTURE_REUSE_DOCUMENTATION.summary },
    schema: [],
    messages: { reuseFixture: "This class is already supplied by the requested `{{fixture}}` fixture; reuse it or request a typed factory for independent instances." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    return {
      NewExpression(node): void {
        const functionNode = requestingFunction(node);
        const call = functionNode === null ? null : directArgumentCall(functionNode);
        if (functionNode === null || call === null) return;
        const parameter = functionNode.params[0];
        if (parameter?.type !== AST_NODE_TYPES.ObjectPattern) return;
        const entries = fixtureApi(context.sourceCode, testApiCallee(call.callee));
        const constructor = constructorBinding(context.sourceCode, node.callee);
        if (entries === null || constructor === null) return;
        for (const property of parameter.properties) {
          if (property.type !== AST_NODE_TYPES.Property || property.computed) continue;
          const name = ASTUtils.getPropertyName(property);
          if (name !== null && entries.get(name) === constructor) {
            context.report({ node, messageId: "reuseFixture", data: { fixture: name } });
            return;
          }
        }
      },
    };
  },
});
