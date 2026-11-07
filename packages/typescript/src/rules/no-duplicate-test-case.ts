/**
 * @fileoverview no-duplicate-test-case — repeated literal rows hide a missing boundary case.
 *
 * Port of the 18.x `no-duplicate-test-case` rule. Same algorithm; the
 * test-file and generated-file gates run in `before()`, which also resets the
 * per-file set of inspected tables.
 */

import { defineRule, type ESTree, type Node, type SourceCode } from "../types.js";
import { outerExpression, parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { vitestFixtureTestName } from "../utils/test-mock-provenance.js";

const NAME = "no-duplicate-test-case";

const TEST_MODULES: ReadonlySet<string> = new Set(["vitest", "@jest/globals", "bun:test"]);
const TEST_NAMES: ReadonlySet<string> = new Set(["it", "test"]);
const MODIFIERS: ReadonlySet<string> = new Set(["only", "skip", "concurrent", "sequential", "fails", "failing", "todo"]);

function frameworkTable(node: ESTree.CallExpression, sourceCode: SourceCode): boolean {
  let callee: Node = unwrapExpression(node.callee);
  if (callee.type !== "MemberExpression") return false;
  const method = getPropertyName(callee);
  if (method !== "each" && method !== "for") return false;
  callee = unwrapExpression(callee.object);
  while (callee.type === "MemberExpression") {
    const name = getPropertyName(callee);
    if (name === null || !MODIFIERS.has(name)) return false;
    callee = unwrapExpression(callee.object);
  }
  if (callee.type !== "Identifier") return false;
  if (vitestFixtureTestName(sourceCode, callee) !== null) return true;
  const variable = findVariable(sourceCode.getScope(callee), callee.name);
  if (variable === null || variable.defs.length === 0) return TEST_NAMES.has(callee.name) && !variable?.references.some(reference => reference.isWrite());
  return variable.defs.length === 1 && variable.defs.every((definition) => {
    if (definition.node.type !== "ImportSpecifier" || definition.node.importKind === "type") return false;
    const imported = definition.node.imported;
    const declaration = definition.node.parent;
    return declaration.type === "ImportDeclaration" && declaration.importKind !== "type" &&
      TEST_NAMES.has(imported.type === "Identifier" ? imported.name : imported.value) &&
      (method === "for" ? declaration.source.value === "vitest" : TEST_MODULES.has(declaration.source.value));
  });
}

function table(node: Node, sourceCode: SourceCode): ESTree.ArrayExpression | null {
  node = unwrapExpression(node);
  if (node.type === "ArrayExpression") return node;
  if (node.type !== "Identifier") return null;
  const variable = findVariable(sourceCode.getScope(node), node.name);
  const definition = variable?.defs[0];
  if (variable?.defs.length !== 1 || definition?.node.type !== "VariableDeclarator" ||
      definition.node.id.type !== "Identifier" || (definition.node.parent as ESTree.VariableDeclaration).kind !== "const" ||
      definition.node.init === null || definition.node.init.range[1] > node.range[0]) return null;
  if (!variable.references.every((reference) => {
    if (reference.init) return true;
    if (reference.identifier.type !== "Identifier") return false;
    const use = outerExpression(reference.identifier);
    const call = parentOf(use);
    return call?.type === "CallExpression" && call.arguments[0] === use && frameworkTable(call, sourceCode);
  })) return null;
  const initializer = unwrapExpression(definition.node.init);
  return initializer.type === "ArrayExpression" ? initializer : null;
}

function literalKey(node: Node): string | null {
  node = unwrapExpression(node);
  switch (node.type) {
    case "Literal":
      return "regex" in node ? null : `${typeof node.value}:${String(node.value)}`;
    case "TemplateLiteral":
      return node.expressions.length === 0 ? `string:${node.quasis[0]?.value.cooked}` : null;
    case "UnaryExpression": {
      const operand = literalKey(node.argument);
      return ["+", "-"].includes(node.operator) && operand !== null ? JSON.stringify([node.operator, operand]) : null;
    }
    case "ArrayExpression": {
      const elements = node.elements.map((element) => element === null ? null : literalKey(element));
      return elements.includes(null) ? null : JSON.stringify(["array", elements]);
    }
    case "ObjectExpression": return objectKey(node);
    default: return null;
  }
}

function objectKey(node: ESTree.ObjectExpression): string | null {
  const fields: string[] = [];
  for (const property of node.properties) {
    if (property.type !== "Property" || property.computed || property.kind !== "init" || property.method) return null;
    const key = getPropertyName(property);
    const value = literalKey(property.value);
    if (key === null || value === null) return null;
    fields.push(JSON.stringify([key, value]));
  }
  return JSON.stringify(["object", fields]);
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {description: "Report repeated literal rows in framework each tables and Vitest for tables.", url: docsUrl(NAME)},
    schema: [],
    messages: {duplicateCase: "This literal row repeats case {{first}} with the same inputs and expected values. Remove the accidental copy or add the intended distinct boundary; preserve intentional repetition explicitly."},
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let inspected = new Set<ESTree.ArrayExpression>();
    return {
      before(): boolean | void {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, sourceCode.text)) return false;
        inspected = new Set<ESTree.ArrayExpression>();
      },
      CallExpression(node: ESTree.CallExpression): void {
        const callee = unwrapExpression(node.callee);
        if (callee.type !== "CallExpression" || !frameworkTable(callee, sourceCode)) return;
        const input = callee.arguments[0];
        if (callee.arguments.length !== 1 || input === undefined) return;
        const cases = table(input, sourceCode);
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
