/**
 * @fileoverview production-derived-test-cases — Keep an independent membership oracle when production collections supply test cases.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/production-derived-test-cases.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { vitestFixtureTestName } from "./_test-mock-provenance.js";
import { unwrapExpression } from "./_unwrap-expression.js";

const MEMBERSHIP = /(?:^|_)(?:ALLOWED|ELIGIBLE|REQUIRED|SUPPORTED)(?:_|$)/u;
const SUPPORT_PATH = /(?:^|[/_.-])(?:tests?|fixtures?|fakes?|mocks?|stubs?|__tests__)(?:[/_.-]|$)/u;

export const PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep an independent membership oracle when production collections supply test cases.",
  rationale: "A test table copied from the production allowed or supported collection changes together with that collection, so removed members silently remove their test cases.",
  remediation: "Declare a literal expected membership table, assert the production collection equals it, and drive cases from that table. Keep deliberate dynamic sweeps with an explained local suppression.",
  category: "testing",
  limitations: [
    "Checks direct first-party relative runtime imports named ALLOWED, ELIGIBLE, REQUIRED or SUPPORTED with underscore-delimited words, passed directly to Vitest each/for tables. Resolves test/it import aliases and unchanged local test.extend runners. Registries, enum introspection, third-party imports and test-support imports remain excluded.",
    "An unconditional module or directly registered test assertion using imported Vitest expect and toEqual/toStrictEqual against a literal array supplies an independent oracle. A stable local const literal table is also accepted when every read belongs to a recognized expectation or case table. Helper-indirected assertions and mutable/captured tables remain outside this bounded proof.",
    "This is a membership-contract review advisory, not a deletion instruction. It does not infer exhaustive coverage, read imported source or automatically remove dynamically generated tests. Generated/vendor files are excluded.",
  ],
  examples: [
    { id: "production-cases", title: "Missing production entries also disappear from these cases", outcome: "match", files: [{ path: "src/roles.test.ts", source: "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; test.each(SUPPORTED_ROLES)('%s', role => { expect(build(role)).toBeDefined(); });" }], focusPath: "src/roles.test.ts", expectedCount: 1, public: true },
    { id: "independent-membership", title: "An independent assertion notices missing entries", outcome: "no-match", files: [{ path: "src/roles.test.ts", source: "import { test, expect } from 'vitest'; import { SUPPORTED_ROLES } from './roles.js'; test('membership', () => { expect(SUPPORTED_ROLES).toEqual(['reader', 'writer']); }); test.each(SUPPORTED_ROLES)('%s', role => { expect(build(role)).toBeDefined(); });" }], focusPath: "src/roles.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "independentCases">({
  name: "production-derived-test-cases",
  documentation: PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PRODUCTION_DERIVED_TEST_CASES_DOCUMENTATION.summary },
    schema: [],
    messages: { independentCases: "`{{name}}` supplies its own production membership cases. Assert its membership against an independent literal table, or explain why this is an intentional dynamic sweep." },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context) || isGeneratedFile(context, context.sourceCode.text)) return {};
    const sourceCode = context.sourceCode;
    const tables: { readonly node: TSESTree.CallExpression; readonly variable: TSESLint.Scope.Variable }[] = [];
    const asserted = new Set<TSESLint.Scope.Variable>();
    function binding(node: TSESTree.Identifier): TSESLint.Scope.Variable | null {
      return ASTUtils.findVariable(sourceCode.getScope(node), node.name);
    }
    function importedName(node: TSESTree.Identifier, module: string): string | null {
      const variable = binding(node);
      const specifier = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || specifier?.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type" ||
        specifier.parent.type !== AST_NODE_TYPES.ImportDeclaration || specifier.parent.importKind === "type" || specifier.parent.source.value !== module ||
        variable.references.some(reference => reference.isWrite())) return null;
      return specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
    }
    function production(node: TSESTree.Node): TSESLint.Scope.Variable | null {
      node = unwrapExpression(node);
      if (node.type !== AST_NODE_TYPES.Identifier) return null;
      const variable = binding(node);
      const specifier = variable?.defs[0]?.node;
      if (variable?.defs.length !== 1 || specifier?.type !== AST_NODE_TYPES.ImportSpecifier || specifier.importKind === "type" ||
        specifier.parent.type !== AST_NODE_TYPES.ImportDeclaration || specifier.parent.importKind === "type" ||
        !specifier.parent.source.value.startsWith(".") || SUPPORT_PATH.test(specifier.parent.source.value) || variable.references.some(reference => reference.isWrite())) return null;
      const name = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
      return MEMBERSHIP.test(name) && !name.endsWith("REGISTRY") ? variable : null;
    }
    function runner(node: TSESTree.Node): boolean {
      node = unwrapExpression(node);
      while (node.type === AST_NODE_TYPES.MemberExpression && ["only", "skip", "concurrent", "sequential"].includes(ASTUtils.getPropertyName(node) ?? "")) node = unwrapExpression(node.object);
      if (node.type !== AST_NODE_TYPES.Identifier) return false;
      const name = importedName(node, "vitest");
      return name === "test" || name === "it" || vitestFixtureTestName(sourceCode, node) !== null;
    }
    function caseTable(node: TSESTree.Node): boolean {
      return node.type === AST_NODE_TYPES.CallExpression && node.callee.type === AST_NODE_TYPES.MemberExpression &&
        ["each", "for"].includes(ASTUtils.getPropertyName(node.callee) ?? "") && runner(node.callee.object);
    }
    function literalTable(node: TSESTree.Node, seen = new Set<TSESTree.Node>()): boolean {
      node = unwrapExpression(node);
      if (seen.has(node)) return false;
      seen.add(node);
      if (node.type === AST_NODE_TYPES.Identifier) {
        const variable = binding(node);
        const definition = variable?.defs[0]?.node;
        return variable?.defs.length === 1 && definition?.type === AST_NODE_TYPES.VariableDeclarator &&
          definition.parent.kind === "const" && definition.init !== null && definition.range[1] < node.range[0] &&
          variable.references.every(reference => reference.init || (!reference.isWrite() && reference.identifier.parent.type === AST_NODE_TYPES.CallExpression &&
            (caseTable(reference.identifier.parent) || reference.identifier.parent.callee.type === AST_NODE_TYPES.Identifier && importedName(reference.identifier.parent.callee, "vitest") === "expect" ||
              reference.identifier.parent.callee.type === AST_NODE_TYPES.MemberExpression && ["toEqual", "toStrictEqual"].includes(ASTUtils.getPropertyName(reference.identifier.parent.callee) ?? "")))) &&
          literalTable(definition.init, seen);
      }
      return node.type === AST_NODE_TYPES.ArrayExpression && node.elements.every(element => element?.type === AST_NODE_TYPES.Literal && !("regex" in element));
    }
    function unconditional(node: TSESTree.CallExpression): boolean {
      const statement = node.parent;
      if (statement.type !== AST_NODE_TYPES.ExpressionStatement) return false;
      if (statement.parent.type === AST_NODE_TYPES.Program) return true;
      const block = statement.parent;
      if (block.type !== AST_NODE_TYPES.BlockStatement ||
        (block.parent.type !== AST_NODE_TYPES.ArrowFunctionExpression && block.parent.type !== AST_NODE_TYPES.FunctionExpression)) return false;
      const call = block.parent.parent;
      return call.type === AST_NODE_TYPES.CallExpression && runner(call.callee);
    }
    return {
      CallExpression(node): void {
        if (caseTable(node) && node.arguments.length === 1 && node.arguments[0] !== undefined) {
          const variable = production(node.arguments[0]);
          if (variable !== null) tables.push({ node, variable });
        }
        if (node.callee.type !== AST_NODE_TYPES.MemberExpression || !["toEqual", "toStrictEqual"].includes(ASTUtils.getPropertyName(node.callee) ?? "") ||
          node.arguments.length !== 1 || node.arguments[0] === undefined || !literalTable(node.arguments[0]) || !unconditional(node)) return;
        const expect = node.callee.object;
        if (expect.type !== AST_NODE_TYPES.CallExpression || expect.callee.type !== AST_NODE_TYPES.Identifier || importedName(expect.callee, "vitest") !== "expect" ||
          expect.arguments.length !== 1 || expect.arguments[0] === undefined) return;
        const variable = production(expect.arguments[0]);
        if (variable !== null) asserted.add(variable);
      },
      "Program:exit"(): void {
        for (const { node, variable } of tables) if (!asserted.has(variable)) context.report({ node, messageId: "independentCases", data: { name: variable.name } });
      },
    };
  },
});
