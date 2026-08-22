/**
 * @fileoverview no-bare-return-from-test-catch — returning from a caught failure can silently pass the rest of a test.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-bare-return-from-test-catch.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "bareReturnFromTestCatch";
type Options = readonly [];
type FunctionNode = TSESTree.ArrowFunctionExpression | TSESTree.FunctionExpression;
type Context = Readonly<TSESLint.RuleContext<MessageIds, Options>>;

export const NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION = {
  summary: "Disallow a bare return from a test catch block when it skips a later assertion.",
  rationale: "The caught failure turns into a passing test without executing the assertion that follows it.",
  remediation: "Rethrow the error, assert on it, or use the runner's explicit skip mechanism when the capability is optional.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only bare returns owned by a direct supported test callback and followed lexically by a framework assertion are reported."],
  examples: [
    { id: "rethrow", title: "Preserve the failure", outcome: "no-match", files: [{ path: "src/codec.test.ts", source: "test('decodes', () => { try { decode(); } catch (error) { throw error; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 0, public: true },
    { id: "bare-return", title: "Do not silently pass", outcome: "match", files: [{ path: "src/codec.test.ts", source: "test('decodes', () => { try { decode(); } catch { return; } expect(result()).toBe('ok'); });" }], focusPath: "src/codec.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const TEST_MODULES: ReadonlySet<string> = new Set(["@jest/globals", "@playwright/test", "bun:test", "node:test", "vitest"]);
const ASSERTION_MODULES: ReadonlySet<string> = new Set([...TEST_MODULES, "node:assert", "node:assert/strict"]);
const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const TEST_MODIFIERS: ReadonlySet<string> = new Set(["concurrent", "fails", "only", "sequential", "skip"]);
const ASSERTION_NAMES: ReadonlySet<string> = new Set(["assert", "assertType", "expect", "expectTypeOf"]);
const FUNCTION_TYPES: ReadonlySet<AST_NODE_TYPES> = new Set([AST_NODE_TYPES.ArrowFunctionExpression, AST_NODE_TYPES.FunctionExpression, AST_NODE_TYPES.FunctionDeclaration]);

function staticMemberName(node: TSESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === AST_NODE_TYPES.Identifier) return node.property.name;
  if (node.computed && node.property.type === AST_NODE_TYPES.Literal && typeof node.property.value === "string") return node.property.value;
  return null;
}

function importedName(identifier: TSESTree.Identifier, context: Context, modules: ReadonlySet<string>): string | null {
  const variable = ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length === 0) return identifier.name;
  for (const definition of variable.defs) {
    if (definition.node.type !== AST_NODE_TYPES.ImportSpecifier) continue;
    const declaration = definition.node.parent;
    if (declaration.type !== AST_NODE_TYPES.ImportDeclaration || typeof declaration.source.value !== "string" || !modules.has(declaration.source.value)) continue;
    if (declaration.source.value === "node:assert" || declaration.source.value === "node:assert/strict") return "assert";
    const imported = definition.node.imported;
    return imported.type === AST_NODE_TYPES.Identifier ? imported.name : String(imported.value);
  }
  return null;
}

function rootIdentifier(callee: TSESTree.Node): TSESTree.Identifier | null {
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type === AST_NODE_TYPES.MemberExpression || callee.type === AST_NODE_TYPES.CallExpression) return rootIdentifier(callee.type === AST_NODE_TYPES.MemberExpression ? callee.object : callee.callee);
  return null;
}

function isDirectTestCallback(node: TSESTree.Node, context: Context): node is FunctionNode {
  if (node.type !== AST_NODE_TYPES.ArrowFunctionExpression && node.type !== AST_NODE_TYPES.FunctionExpression) return false;
  const call = node.parent;
  if (call?.type !== AST_NODE_TYPES.CallExpression || !call.arguments.includes(node)) return false;
  const root = testRoot(call.callee);
  return root !== null && TEST_NAMES.has(importedName(root, context, TEST_MODULES) ?? "");
}

function testRoot(callee: TSESTree.Node): TSESTree.Identifier | null {
  if (callee.type === AST_NODE_TYPES.Identifier) return callee;
  if (callee.type !== AST_NODE_TYPES.MemberExpression) return null;
  const modifier = staticMemberName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier) ? testRoot(callee.object) : null;
}

function nearestFunction(node: TSESTree.Node): TSESTree.Node | null {
  for (let current = node.parent; current !== undefined && current !== null; current = current.parent) if (FUNCTION_TYPES.has(current.type)) return current;
  return null;
}

function walkOwnScope(node: TSESTree.Node, predicate: (current: TSESTree.Node) => boolean): boolean {
  if (predicate(node)) return true;
  for (const key of Object.keys(node)) {
    if (key === "parent") continue;
    const value = (node as unknown as Record<string, unknown>)[key];
    for (const child of Array.isArray(value) ? value : [value]) {
      if (typeof child === "object" && child !== null && typeof (child as { type?: unknown }).type === "string") {
        const childNode = child as TSESTree.Node;
        if (!FUNCTION_TYPES.has(childNode.type) && walkOwnScope(childNode, predicate)) return true;
      }
    }
  }
  return false;
}

function isAssertion(node: TSESTree.Node, context: Context): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression) return false;
  const root = rootIdentifier(node.callee);
  return root !== null && ASSERTION_NAMES.has(importedName(root, context, ASSERTION_MODULES) ?? "");
}

function isExplicitSkip(node: TSESTree.Node, context: Context): boolean {
  if (node.type !== AST_NODE_TYPES.CallExpression || node.callee.type !== AST_NODE_TYPES.MemberExpression || staticMemberName(node.callee) !== "skip") return false;
  const root = rootIdentifier(node.callee.object);
  return root !== null && TEST_NAMES.has(importedName(root, context, TEST_MODULES) ?? "");
}

export default createRule<Options, MessageIds>({
  name: "no-bare-return-from-test-catch",
  documentation: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: "Disallow a bare return from a test catch block when it skips a later assertion." },
    schema: [],
    messages: { bareReturnFromTestCatch: "This bare return turns the caught failure into a passing test and skips a later assertion. Rethrow, assert on the error, or explicitly skip the test." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    return {
      ReturnStatement(node: TSESTree.ReturnStatement): void {
        if (node.argument !== null) return;
        const owner = nearestFunction(node);
        if (owner === null || !isDirectTestCallback(owner, context)) return;
        let catchClause: TSESTree.CatchClause | null = null;
        for (let current: TSESTree.Node | null | undefined = node.parent; current !== owner; current = current?.parent) {
          if (current?.type === AST_NODE_TYPES.CatchClause) { catchClause = current; break; }
          if (current === null || current === undefined) break;
        }
        if (catchClause === null || catchClause.parent.finalizer !== null) return;
        if (walkOwnScope(catchClause.body, (current) => current.type === AST_NODE_TYPES.ThrowStatement || isExplicitSkip(current, context))) return;
        if (!walkOwnScope(owner.body, (current) => current.range[0] > node.range[1] && isAssertion(current, context))) return;
        context.report({ node, messageId: "bareReturnFromTestCatch" });
      },
    };
  },
});
