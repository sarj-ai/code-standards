/**
 * @fileoverview production-derived-test-cases — Keep an independent membership oracle when production collections supply test cases.
 *
 * Port of the 18.x `production-derived-test-cases` rule. File gates and
 * per-file state move to `before()`; the analysis is unchanged.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/production-derived-test-cases.test.ts
 */

import { defineRule, type ESTree, type Node, type SourceCode, type TsVariable } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { docsUrl } from "../utils/docs-url.js";
import { importSpecifierName } from "../utils/import-specifier-name.js";
import { isGeneratedFile, isTestFile } from "../utils/paths.js";
import { findVariable, getPropertyName } from "../utils/static-string.js";
import { vitestFixtureTestName } from "../utils/test-mock-provenance.js";

type Identifier = Extract<Node, { type: "Identifier" }>;

const MEMBERSHIP = /(?:^|_)(?:ALLOWED|ELIGIBLE|REQUIRED|SUPPORTED)(?:_|$)/u;
const SUPPORT_PATH = /(?:^|[/_.-])(?:tests?|fixtures?|fakes?|mocks?|stubs?|__tests__)(?:[/_.-]|$)/u;
const RUNNER_MODIFIERS: readonly string[] = ["only", "skip", "concurrent", "sequential"];
const TABLE_METHODS: readonly string[] = ["each", "for"];
const EQUALITY_MATCHERS: readonly string[] = ["toEqual", "toStrictEqual"];

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Keep an independent membership oracle when production collections supply test cases.",
      url: docsUrl("production-derived-test-cases"),
    },
    schema: [],
    messages: { independentCases: "`{{name}}` supplies its own production membership cases. Assert its membership against an independent literal table, or explain why this is an intentional dynamic sweep." },
  },
  createOnce(context) {
    let sourceCode: SourceCode;
    let tables: { readonly node: ESTree.CallExpression; readonly variable: TsVariable }[] = [];
    let asserted = new Set<TsVariable>();

    function binding(node: Identifier): TsVariable | null {
      return findVariable(sourceCode.getScope(node), node.name);
    }

    /** The import specifier behind a sole-definition, never-written binding. */
    function importSpecifier(variable: TsVariable | null): { specifier: ESTree.ImportSpecifier; declaration: ESTree.ImportDeclaration } | null {
      const specifier = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || specifier?.type !== "ImportSpecifier" || specifier.importKind === "type") return null;
      const declaration = parentOf(specifier);
      if (declaration?.type !== "ImportDeclaration" || declaration.importKind === "type") return null;
      return { specifier, declaration };
    }

    function importedName(node: Identifier, module: string): string | null {
      const variable = binding(node);
      const imported = importSpecifier(variable);
      if (imported === null || imported.declaration.source.value !== module ||
        variable?.references.some(reference => reference.isWrite())) return null;
      return importSpecifierName(imported.specifier);
    }

    function production(start: Node): TsVariable | null {
      const node = unwrapExpression(start);
      if (node.type !== "Identifier") return null;
      const variable = binding(node);
      const imported = importSpecifier(variable);
      if (variable === null || imported === null) return null;
      const source = imported.declaration.source.value;
      if (!source.startsWith(".") || SUPPORT_PATH.test(source) || variable.references.some(reference => reference.isWrite())) return null;
      const name = importSpecifierName(imported.specifier);
      return MEMBERSHIP.test(name) && !name.endsWith("REGISTRY") ? variable : null;
    }

    function runner(start: Node): boolean {
      let node = unwrapExpression(start);
      while (node.type === "MemberExpression" && RUNNER_MODIFIERS.includes(getPropertyName(node) ?? "")) node = unwrapExpression(node.object);
      if (node.type !== "Identifier") return false;
      const name = importedName(node, "vitest");
      return name === "test" || name === "it" || vitestFixtureTestName(sourceCode, node) !== null;
    }

    function caseTable(node: Node): boolean {
      return node.type === "CallExpression" && node.callee.type === "MemberExpression" &&
        TABLE_METHODS.includes(getPropertyName(node.callee) ?? "") && runner(node.callee.object);
    }

    function expectationRead(parent: Node | null): boolean {
      if (parent?.type !== "CallExpression") return false;
      return caseTable(parent) ||
        (parent.callee.type === "Identifier" && importedName(parent.callee, "vitest") === "expect") ||
        (parent.callee.type === "MemberExpression" && EQUALITY_MATCHERS.includes(getPropertyName(parent.callee) ?? ""));
    }

    /** The production collection in an unconditional `expect(collection).toEqual(literalTable)`. */
    function literalAssertionSubject(node: ESTree.CallExpression, expected: ESTree.Argument): TsVariable | null {
      if (node.callee.type !== "MemberExpression" || !EQUALITY_MATCHERS.includes(getPropertyName(node.callee) ?? "") ||
        !literalTable(expected) || !unconditional(node)) return null;
      const expect = node.callee.object;
      if (expect.type !== "CallExpression" || expect.callee.type !== "Identifier" || expect.arguments.length !== 1) return null;
      const [actual] = expect.arguments;
      if (actual === undefined || importedName(expect.callee, "vitest") !== "expect") return null;
      return production(actual);
    }

    function literalTable(start: Node, seen = new Set<Node>()): boolean {
      const node = unwrapExpression(start);
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === "Identifier") return literalTableBinding(node, seen);
      return node.type === "ArrayExpression" && node.elements.every(element => element?.type === "Literal" && !("regex" in element));
    }

    /** An earlier `const` literal table that is only ever read by expectations. */
    function literalTableBinding(node: Identifier, seen: Set<Node>): boolean {
      const variable = binding(node);
      const definition = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || definition?.type !== "VariableDeclarator") return false;
      const declaration = parentOf(definition);
      return declaration?.type === "VariableDeclaration" && declaration.kind === "const" &&
        definition.init !== null && definition.range[1] < node.range[0] &&
        variable.references.every(reference => reference.init || (!reference.isWrite() && expectationRead(parentOf(reference.identifier)))) &&
        literalTable(definition.init, seen);
    }

    function unconditional(node: ESTree.CallExpression): boolean {
      const statement = parentOf(node);
      if (statement?.type !== "ExpressionStatement") return false;
      const block = parentOf(statement);
      if (block?.type === "Program") return true;
      const owner = block === null ? null : parentOf(block);
      if (block?.type !== "BlockStatement" ||
        (owner?.type !== "ArrowFunctionExpression" && owner?.type !== "FunctionExpression")) return false;
      const call = parentOf(owner);
      return call?.type === "CallExpression" && runner(call.callee);
    }

    return {
      before() {
        sourceCode = context.sourceCode;
        const file = { filename: context.filename, cwd: context.cwd };
        if (!isTestFile(file) || isGeneratedFile(file, sourceCode.text)) return false;
        tables = [];
        asserted = new Set();
        return undefined;
      },
      CallExpression(node: ESTree.CallExpression): void {
        const [argument] = node.arguments;
        if (argument === undefined || node.arguments.length !== 1) return;
        if (caseTable(node)) {
          const variable = production(argument);
          if (variable !== null) tables.push({ node, variable });
        }
        const variable = literalAssertionSubject(node, argument);
        if (variable !== null) asserted.add(variable);
      },
      "Program:exit"(): void {
        for (const { node, variable } of tables) if (!asserted.has(variable)) context.report({ node, messageId: "independentCases", data: { name: variable.name } });
      },
    };
  },
});
