/**
 * @fileoverview no-first-party-module-mock — prefer explicit injection over ambient replacement of first-party modules.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-first-party-module-mock.test.ts
 */

import { ASTUtils, AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { unwrapExpression } from "./_unwrap-expression.js";
import { staticString } from "./_static-string.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { importedTestMockNamespace } from "./_test-mock-provenance.js";

type MessageIds = "noFirstPartyModuleMock";
type Options = readonly [{ additionalModulePrefixes?: readonly string[] }];

export const NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION = {
  summary: "Prefer injected collaborators over mocking maintained first-party modules in tests.",
  rationale: "Replacing an owned module couples tests to its lookup path and can verify mock wiring while bypassing the real implementation contract.",
  remediation: "Extract a narrow port or pure core operation and inject a typed fake; retain module mocking only when module lookup or bootstrap behavior is the contract.",
  category: "testing",
  limitations: ["Only generated-free test files, provenance-resolved Vitest or Jest APIs, relative module specifiers, and explicitly configured first-party prefixes are checked. Third-party, framework, Jest virtual modules, unknown Jest options, type-only imports and dynamic module names are excluded. Unimported framework globals and indirect namespace aliases are not inferred."],
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
    return {
      CallExpression(node: TSESTree.CallExpression): void {
        const unwrappedNodeCallee = unwrapExpression(node.callee);
        const receiver = unwrappedNodeCallee.type === AST_NODE_TYPES.MemberExpression ? unwrapExpression(unwrappedNodeCallee.object) : unwrappedNodeCallee;
        if (unwrappedNodeCallee.type !== AST_NODE_TYPES.MemberExpression || receiver.type !== AST_NODE_TYPES.Identifier || ASTUtils.getPropertyName(unwrappedNodeCallee) === null || !["mock", "doMock"].includes((ASTUtils.getPropertyName(unwrappedNodeCallee) ?? ""))) return;
        const framework = importedTestMockNamespace(context.sourceCode, receiver);
        if (framework === null || (framework === "jest" && mayBeVirtual(node.arguments[2]))) return;
        const argument = node.arguments[0] === undefined ? undefined : unwrapExpression(node.arguments[0]);
        const moduleName = staticString(argument);
        if (argument === undefined || moduleName === null) return;
        if (!isFirstParty(moduleName, options.additionalModulePrefixes ?? [])) return;
        context.report({ node: argument, messageId: "noFirstPartyModuleMock", data: { module: moduleName } });
      },
    };
  },
});

function mayBeVirtual(options: TSESTree.CallExpressionArgument | undefined): boolean {
  if (options === undefined) return false;
  if (options.type !== AST_NODE_TYPES.ObjectExpression) return true;
  return options.properties.some((property) => {
    if (property.type !== AST_NODE_TYPES.Property || property.computed) return true;
    const name = property.key.type === AST_NODE_TYPES.Identifier ? property.key.name : property.key.type === AST_NODE_TYPES.Literal ? property.key.value : null;
    return name === "virtual" && !(property.value.type === AST_NODE_TYPES.Literal && property.value.value === false);
  });
}
