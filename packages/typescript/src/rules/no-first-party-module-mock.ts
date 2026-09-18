/**
 * @fileoverview no-first-party-module-mock — prefer explicit injection over ambient replacement of first-party modules.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-first-party-module-mock.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";

type MessageIds = "noFirstPartyModuleMock";
type Options = readonly [{ additionalModulePrefixes?: readonly string[] }];

export const NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION = {
  summary: "Prefer injected collaborators over mocking maintained first-party modules in tests.",
  rationale: "Replacing an owned module couples tests to its lookup path and can verify mock wiring while bypassing the real implementation contract.",
  remediation: "Extract a narrow port or pure core operation and inject a typed fake; retain module mocking only when module lookup or bootstrap behavior is the contract.",
  category: "testing",
  limitations: ["Only generated-free test files, provenance-resolved Vitest or Jest APIs, relative module specifiers, and explicitly configured first-party prefixes are checked. Third-party, framework, virtual, and dynamic modules are excluded."],
  examples: [
    { id: "injected-service", title: "Inject a narrow service port", outcome: "no-match", files: [{ path: "action.test.ts", source: "const result = await runAction({ service: recordingService });" }], focusPath: "action.test.ts", expectedCount: 0, public: true },
    { id: "relative-module-mock", title: "Do not replace an owned module", outcome: "match", files: [{ path: "action.test.ts", source: "import { vi } from 'vitest'; vi.mock('./service', () => ({ run: vi.fn() }));" }], focusPath: "action.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function isFirstParty(source: string, prefixes: readonly string[]): boolean {
  return source.startsWith("./") || source.startsWith("../") || prefixes.some((prefix) => source.startsWith(prefix));
}

export default createRule<Options, MessageIds>({
  name: "no-first-party-module-mock",
  documentation: NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION.summary },
    schema: [{ type: "object", additionalProperties: false, properties: { additionalModulePrefixes: { type: "array", items: { type: "string", minLength: 1 }, uniqueItems: true } } }],
    messages: { noFirstPartyModuleMock: "This test replaces the maintained module `{{module}}`. Inject a narrow collaborator or test the real module; suppress locally only when module lookup or bootstrap behavior is the contract." },
  },
  defaultOptions: [{ additionalModulePrefixes: [] }],
  create(context, [options]) {
    if (!isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const namespaces = new Set<TSESLint.Scope.Variable>();
    const resolve = (identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null => ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);
    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (node.source.value !== "vitest" && node.source.value !== "@jest/globals") return;
        for (const specifier of node.specifiers) {
          if (specifier.type !== AST_NODE_TYPES.ImportSpecifier) continue;
          const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
          if (imported !== "vi" && imported !== "jest") continue;
          const binding = resolve(specifier.local);
          if (binding !== null) namespaces.add(binding);
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (node.callee.type !== AST_NODE_TYPES.MemberExpression || node.callee.computed || node.callee.object.type !== AST_NODE_TYPES.Identifier || node.callee.property.type !== AST_NODE_TYPES.Identifier || !["mock", "doMock"].includes(node.callee.property.name)) return;
        const binding = resolve(node.callee.object);
        if (binding === null || !namespaces.has(binding)) return;
        const argument = node.arguments[0];
        if (argument?.type !== AST_NODE_TYPES.Literal || typeof argument.value !== "string") return;
        if (!isFirstParty(argument.value, options.additionalModulePrefixes ?? [])) return;
        context.report({ node: argument, messageId: "noFirstPartyModuleMock", data: { module: argument.value } });
      },
    };
  },
});
