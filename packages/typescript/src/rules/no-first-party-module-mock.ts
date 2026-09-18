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
type Framework = "jest" | "vitest";

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

function staticMemberName(member: TSESTree.MemberExpression): string | null {
  if (!member.computed && member.property.type === AST_NODE_TYPES.Identifier) return member.property.name;
  return member.computed && member.property.type === AST_NODE_TYPES.Literal && typeof member.property.value === "string"
    ? member.property.value
    : null;
}

function staticModule(node: TSESTree.Node | undefined): string | null {
  if (node?.type === AST_NODE_TYPES.Literal && typeof node.value === "string") return node.value;
  if (node?.type === AST_NODE_TYPES.TemplateLiteral && node.expressions.length === 0) return node.quasis[0]?.value.cooked ?? null;
  return node?.type === AST_NODE_TYPES.ImportExpression ? staticModule(node.source) : null;
}

function importedFramework(source: string, imported: string): Framework | null {
  if (source === "vitest" && imported === "vi") return "vitest";
  return source === "@jest/globals" && imported === "jest" ? "jest" : null;
}

function supportsMockMethod(framework: Framework, method: string): boolean {
  return method === "mock" || method === "doMock" ||
    (framework === "jest" && (method === "setMock" || method === "unstable_mockModule"));
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
    const namespaces = new Map<TSESLint.Scope.Variable, Framework>();
    const moduleNamespaces = new Map<TSESLint.Scope.Variable, Framework>();
    const resolve = (identifier: TSESTree.Identifier): TSESLint.Scope.Variable | null => ASTUtils.findVariable(context.sourceCode.getScope(identifier), identifier.name);

    function receiverFramework(receiver: TSESTree.Node): Framework | null {
      if (receiver.type === AST_NODE_TYPES.Identifier) {
        const binding = resolve(receiver);
        return binding === null ? null : namespaces.get(binding) ?? null;
      }
      if (receiver.type !== AST_NODE_TYPES.MemberExpression || receiver.object.type !== AST_NODE_TYPES.Identifier) return null;
      const binding = resolve(receiver.object);
      if (binding === null) return null;
      const framework = moduleNamespaces.get(binding);
      if (framework === undefined) return null;
      const expectedNamespace = framework === "vitest" ? "vi" : "jest";
      return staticMemberName(receiver) === expectedNamespace ? framework : null;
    }

    return {
      ImportDeclaration(node: TSESTree.ImportDeclaration): void {
        if (node.source.value !== "vitest" && node.source.value !== "@jest/globals") return;
        const sourceFramework: Framework = node.source.value === "vitest" ? "vitest" : "jest";
        for (const specifier of node.specifiers) {
          if (specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier) {
            const binding = resolve(specifier.local);
            if (binding !== null) moduleNamespaces.set(binding, sourceFramework);
            continue;
          }
          if (specifier.type !== AST_NODE_TYPES.ImportSpecifier) continue;
          const imported = specifier.imported.type === AST_NODE_TYPES.Identifier ? specifier.imported.name : specifier.imported.value;
          const framework = importedFramework(node.source.value, imported);
          if (framework === null) continue;
          const binding = resolve(specifier.local);
          if (binding !== null) namespaces.set(binding, framework);
        }
      },
      CallExpression(node: TSESTree.CallExpression): void {
        if (node.callee.type !== AST_NODE_TYPES.MemberExpression) return;
        const framework = receiverFramework(node.callee.object);
        const method = staticMemberName(node.callee);
        if (framework === null || method === null || !supportsMockMethod(framework, method)) return;
        const argument = node.arguments[0];
        if (argument === undefined) return;
        const module = staticModule(argument);
        if (module === null || !isFirstParty(module, options.additionalModulePrefixes ?? [])) return;
        context.report({ node: argument, messageId: "noFirstPartyModuleMock", data: { module } });
      },
    };
  },
});
