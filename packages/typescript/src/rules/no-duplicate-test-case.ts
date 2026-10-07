/**
 * @fileoverview no-duplicate-test-case — repeated literal rows hide a missing boundary case.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-duplicate-test-case.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

type Options = readonly [];
type MessageIds = "duplicateCase";

const TEST_MODULES: ReadonlySet<string> = new Set(["vitest", "@jest/globals", "bun:test"]);
const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const MODIFIERS: ReadonlySet<string> = new Set(["only", "skip", "concurrent", "fails", "failing", "todo"]);

export const NO_DUPLICATE_TEST_CASE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Report repeated literal rows in framework test.each or it.each tables.",
  rationale: "Identical rows repeat the same inputs and expected values without exposing a distinct case. Accidental duplicates consume test time and hide a missing boundary vector.",
  remediation: "Remove the accidental duplicate or replace it with the intended distinct boundary. Preserve intentional repeated or stateful scenarios with a local explanation; do not delete their coverage automatically.",
  category: "testing",
  limitations: [
    "Only literal rows in inline arrays or const tables used exclusively by each calls are compared. Calls, spreads, computed keys, getters, runtime values, tagged tables and mutable or escaped tables are excluded.",
    "Object property order and all row fields, including names and IDs, remain part of case identity. Imported test aliases are resolved; custom runners and namespace imports are excluded.",
    "The rule reports duplicate values, not runtime equivalence. There is no autofix because repeated invocations may exercise shared state or concurrency.",
  ],
  examples: [
    {id: "duplicate-row", title: "A copied row misses the intended boundary", outcome: "match", files: [{path: "src/format.test.ts", source: "import {it} from 'vitest'; it.each([[0, '0ms'], [0, '0ms']])('%s', (input, expected) => { expect(format(input)).toBe(expected); });"}], focusPath: "src/format.test.ts", expectedCount: 1, public: true},
    {id: "distinct-boundary", title: "Distinct inputs have independent rows", outcome: "no-match", files: [{path: "src/format.test.ts", source: "import {it} from 'vitest'; it.each([[0, '0ms'], [1, '1ms']])('%s', (input, expected) => { expect(format(input)).toBe(expected); });"}], focusPath: "src/format.test.ts", expectedCount: 0, public: true},
  ],
} as const satisfies RuleDocumentation;

function frameworkEach(node: TSESTree.CallExpression, sourceCode: Readonly<TSESLint.SourceCode>): boolean {
  let callee: TSESTree.Node = unwrapExpression(node.callee);
  if (callee.type !== AST_NODE_TYPES.MemberExpression || ASTUtils.getPropertyName(callee) !== "each") return false;
  callee = unwrapExpression(callee.object);
  while (callee.type === AST_NODE_TYPES.MemberExpression) {
    const name = ASTUtils.getPropertyName(callee);
    if (name === null || !MODIFIERS.has(name)) return false;
    callee = unwrapExpression(callee.object);
  }
  if (callee.type !== AST_NODE_TYPES.Identifier) return false;
  const variable = ASTUtils.findVariable(sourceCode.getScope(callee), callee.name);
  if (variable === null || variable.defs.length === 0) return TEST_NAMES.has(callee.name);
  return variable.defs.length === 1 && variable.defs.every((definition) => {
    if (definition.node.type !== AST_NODE_TYPES.ImportSpecifier) return false;
    const imported = definition.node.imported;
    const declaration = definition.node.parent;
    return declaration.type === AST_NODE_TYPES.ImportDeclaration && TEST_NAMES.has(imported.type === AST_NODE_TYPES.Identifier ? imported.name : imported.value) &&
      TEST_MODULES.has(declaration.source.value);
  });
}

function table(node: TSESTree.Node, sourceCode: Readonly<TSESLint.SourceCode>): TSESTree.ArrayExpression | null {
  node = unwrapExpression(node);
  if (node.type === AST_NODE_TYPES.ArrayExpression) return node;
  if (node.type !== AST_NODE_TYPES.Identifier) return null;
  const variable = ASTUtils.findVariable(sourceCode.getScope(node), node.name);
  const definition = variable?.defs[0];
  if (variable?.defs.length !== 1 || definition?.node.type !== AST_NODE_TYPES.VariableDeclarator ||
      definition.node.id.type !== AST_NODE_TYPES.Identifier || definition.node.parent.kind !== "const" ||
      definition.node.init === null || definition.node.init.range[1] > node.range[0]) return null;
  if (!variable.references.every((reference) => {
    if (reference.init) return true;
    if (reference.identifier.type !== AST_NODE_TYPES.Identifier) return false;
    const use = outerExpression(reference.identifier);
    return use.parent.type === AST_NODE_TYPES.CallExpression && use.parent.arguments[0] === use && frameworkEach(use.parent, sourceCode);
  })) return null;
  const initializer = unwrapExpression(definition.node.init);
  return initializer.type === AST_NODE_TYPES.ArrayExpression ? initializer : null;
}

function literalKey(node: TSESTree.Node): string | null {
  node = unwrapExpression(node);
  switch (node.type) {
    case AST_NODE_TYPES.Literal:
      return "regex" in node ? null : `${typeof node.value}:${String(node.value)}`;
    case AST_NODE_TYPES.TemplateLiteral:
      return node.expressions.length === 0 ? `string:${node.quasis[0]?.value.cooked}` : null;
    case AST_NODE_TYPES.UnaryExpression: {
      const operand = literalKey(node.argument);
      return ["+", "-"].includes(node.operator) && operand !== null ? JSON.stringify([node.operator, operand]) : null;
    }
    case AST_NODE_TYPES.ArrayExpression: {
      const elements = node.elements.map((element) => element === null ? null : literalKey(element));
      return elements.includes(null) ? null : JSON.stringify(["array", elements]);
    }
    case AST_NODE_TYPES.ObjectExpression: return objectKey(node);
    default: return null;
  }
}

function objectKey(node: TSESTree.ObjectExpression): string | null {
  const fields: string[] = [];
  for (const property of node.properties) {
    if (property.type !== AST_NODE_TYPES.Property || property.computed || property.kind !== "init" || property.method) return null;
    const key = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : literalKey(property.key);
    const value = literalKey(property.value);
    if (key === null || value === null) return null;
    fields.push(JSON.stringify([key, value]));
  }
  return JSON.stringify(["object", fields]);
}

export default createRule<Options, MessageIds>({
  name: "no-duplicate-test-case",
  documentation: NO_DUPLICATE_TEST_CASE_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {description: NO_DUPLICATE_TEST_CASE_DOCUMENTATION.summary},
    schema: [],
    messages: {duplicateCase: "This literal row repeats case {{first}} with the same inputs and expected values. Remove the accidental copy or add the intended distinct boundary; preserve intentional repetition explicitly."},
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const inspected = new Set<TSESTree.ArrayExpression>();
    return {
      CallExpression(node): void {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== AST_NODE_TYPES.CallExpression || !frameworkEach(callee, context.sourceCode)) return;
        const input = callee.arguments[0];
        if (callee.arguments.length !== 1 || input === undefined) return;
        const cases = table(input, context.sourceCode);
        if (cases === null || inspected.has(cases)) return;
        inspected.add(cases);
        const seen = new Map<string, number>();
        for (const [index, row] of cases.elements.entries()) {
          if (row === null) continue;
          const key = literalKey(row);
          if (key === null) continue;
          const first = seen.get(key);
          if (first !== undefined) context.report({node: row, messageId: "duplicateCase", data: {first: first + 1}});
          else seen.set(key, index);
        }
      },
    };
  },
});
