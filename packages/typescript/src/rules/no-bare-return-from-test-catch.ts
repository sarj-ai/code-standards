/**
 * @fileoverview no-bare-return-from-test-catch — returning from a caught failure can silently pass the rest of a test.
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-bare-return-from-test-catch.test.ts
 */

import { sourceOrigin } from "./_source-origin.js";
import type { ESTree, Context } from "@oxlint/plugins";
import { findVariable } from "./_scope.js";


import { forEachOwnAstChild } from "./_for-each-own-ast-child.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "bareReturnFromTestCatch";
type Options = readonly [];
type FunctionNode = ESTree.ArrowFunctionExpression | ESTree.Function;

export const NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION = {
  summary: "Disallow a bare return from a test catch block when it skips a later assertion.",
  rationale: "An unasserted catch return can swallow a failure and skip later assertions; the complete test result also depends on other assertions and hooks.",
  remediation: "Rethrow the error, assert on it, or use the runner's explicit skip mechanism when the capability is optional.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only bare returns owned by a direct supported test callback and followed lexically by a framework assertion are reported. A runner skip suppresses the finding only when it is an unconditional earlier statement in the return's block."],
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
const FUNCTION_TYPES: ReadonlySet<ESTree.Node["type"]> = new Set(["ArrowFunctionExpression", "FunctionExpression", "FunctionDeclaration"]);

function staticMemberName(node: ESTree.MemberExpression): string | null {
  if (!node.computed && node.property.type === "Identifier") return node.property.name;
  if (node.computed && node.property.type === "Literal" && typeof node.property.value === "string") return node.property.value;
  return null;
}

function importedName(identifier: ESTree.BindingIdentifier, context: Context, modules: ReadonlySet<string>): string | null {
  const variable = findVariable(context.sourceCode.getScope(identifier), identifier.name);
  if (variable === null || variable.defs.length === 0) return identifier.name;
  for (const definition of variable.defs) {
    if (
      definition.node.type !== "ImportSpecifier" &&
      definition.node.type !== "ImportDefaultSpecifier" &&
      definition.node.type !== "ImportNamespaceSpecifier"
    ) continue;
    const declaration = definition.node.parent;
    if (declaration.type !== "ImportDeclaration" || typeof declaration.source.value !== "string" || !modules.has(declaration.source.value)) continue;
    if (declaration.source.value === "node:assert" || declaration.source.value === "node:assert/strict") return "assert";
    if (definition.node.type !== "ImportSpecifier") continue;
    const imported = definition.node.imported;
    return imported.type === "Identifier" ? imported.name : String(imported.value);
  }
  return null;
}

function rootIdentifier(callee: ESTree.Node): ESTree.BindingIdentifier | null {
  if (callee.type === "Identifier") return callee;
  if (callee.type === "MemberExpression" || callee.type === "CallExpression") return rootIdentifier(callee.type === "MemberExpression" ? callee.object : callee.callee);
  return null;
}

function isDirectTestCallback(node: ESTree.Node, context: Context): node is FunctionNode {
  if (node.type !== "ArrowFunctionExpression" && node.type !== "FunctionExpression") return false;
  const call = node.parent;
  if (call?.type !== "CallExpression" || !call.arguments.includes(node)) return false;
  const root = testRoot(call.callee);
  return root !== null && TEST_NAMES.has(importedName(root, context, TEST_MODULES) ?? "");
}

function testRoot(callee: ESTree.Node): ESTree.BindingIdentifier | null {
  if (callee.type === "Identifier") return callee;
  if (callee.type !== "MemberExpression") return null;
  const modifier = staticMemberName(callee);
  return modifier !== null && TEST_MODIFIERS.has(modifier) ? testRoot(callee.object) : null;
}

function nearestFunction(node: ESTree.Node): ESTree.Node | null {
  for (let current = node.parent; current != null && current !== null; current = current.parent) if (FUNCTION_TYPES.has(current.type)) return current;
  return null;
}

function walkOwnScope(node: ESTree.Node, predicate: (current: ESTree.Node) => boolean): boolean {
  if (predicate(node)) return true;
  return forEachOwnAstChild(node, child =>
    !FUNCTION_TYPES.has(child.type) && walkOwnScope(child, predicate));
}

function isAssertion(node: ESTree.Node, context: Context): boolean {
  if (node.type !== "CallExpression") return false;
  const root = rootIdentifier(node.callee);
  return root !== null && ASSERTION_NAMES.has(importedName(root, context, ASSERTION_MODULES) ?? "");
}

function isExplicitSkip(node: ESTree.Node, context: Context): boolean {
  if (node.type !== "CallExpression" || node.callee.type !== "MemberExpression" || staticMemberName(node.callee) !== "skip") return false;
  const root = rootIdentifier(node.callee.object);
  return root !== null && TEST_NAMES.has(importedName(root, context, TEST_MODULES) ?? "");
}

function hasDominatingExplicitSkip(
  node: ESTree.ReturnStatement,
  context: Context,
): boolean {
  const block = node.parent;
  if (block?.type !== "BlockStatement") return false;
  return block.body.some(
    (candidate) =>
      candidate.range[1] <= node.range[0] &&
      candidate.type === "ExpressionStatement" &&
      isExplicitSkip(candidate.expression, context),
  );
}

export default createRule<Options, MessageIds>({
  name: "no-bare-return-from-test-catch",
  documentation: NO_BARE_RETURN_FROM_TEST_CATCH_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: "Disallow a bare return from a test catch block when it skips a later assertion." },
    schema: [],
    messages: { bareReturnFromTestCatch: "This bare return can swallow the caught failure and skips a later assertion. Rethrow, assert on the error, or explicitly skip the test." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(sourceOrigin(context).filename) || isGeneratedFile(sourceOrigin(context).filename, sourceOrigin(context).text)) return {};
    return {
      ReturnStatement(node: ESTree.ReturnStatement): void {
        if (node.argument !== null) return;
        const owner = nearestFunction(node);
        if (owner === null || !isDirectTestCallback(owner, context)) return;
        let catchClause: ESTree.CatchClause | null = null;
        for (let current: ESTree.Node | null | undefined = node.parent; current !== owner; current = current?.parent) {
          if (current?.type === "CatchClause") { catchClause = current; break; }
          if (current === null || current == null) break;
        }
        if (catchClause === null) return;
        const parameter = catchClause.param;
        const returnBlock = node.parent;
        if (parameter?.type === "Identifier" && returnBlock?.type === "BlockStatement") {
          const errorBinding = findVariable(context.sourceCode.getScope(parameter), parameter.name);
          const assertedError = returnBlock.body.some((statement) => {
            if (statement.range[1] >= node.range[0] || statement.type !== "ExpressionStatement") return false;
            const expression = statement.expression;
            if (expression.type !== "CallExpression" || !isAssertion(expression, context)) return false;
            const root = rootIdentifier(expression.callee);
            if (root === null) return false;
            const assertionName = importedName(root, context, ASSERTION_MODULES);
            let operand = expression.callee.type === "MemberExpression" ? expression.callee.object : null;
            if (operand?.type === "MemberExpression" && staticMemberName(operand) === "not") operand = operand.object;
            if (assertionName !== "assert" && (assertionName !== "expect" || operand?.type !== "CallExpression" || operand.callee !== root)) return false;
            return walkOwnScope(expression, (current) => current.type === "Identifier" && errorBinding?.references.some((reference) => reference.identifier === current) === true);
          });
          if (assertedError) return;
        }
        if (hasDominatingExplicitSkip(node, context)) return;
        if (owner.body === null || !walkOwnScope(owner.body, (current) => current.range[0] > node.range[1] && isAssertion(current, context))) return;
        context.report({ node, messageId: "bareReturnFromTestCatch" });
      },
    };
  },
});
