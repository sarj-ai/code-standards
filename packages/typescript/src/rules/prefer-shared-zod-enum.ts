/**
 * @fileoverview prefer-shared-zod-enum — repeated literal enum domains can drift within one module.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-shared-zod-enum.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "shareEnumDomain";
type Options = [];

export const PREFER_SHARED_ZOD_ENUM_DOCUMENTATION = {
  summary: "Reuse identical literal Zod enum domains within a module.",
  rationale: "Repeating the same literal domain creates parallel contracts that can drift independently.",
  remediation: "Declare one module-level named Zod enum schema and reuse it at each field or contract site.",
  category: "maintainability",
  limitations: ["Only direct z.enum calls with ordered string-literal arrays in the same module are compared."],
  examples: [
    { id: "shared-provider", title: "Reuse a named enum schema", outcome: "no-match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const ProviderSchema = z.enum(['agy', 'claude', 'sol']); const JobSchema = z.object({ provider: ProviderSchema }); const StatusSchema = z.object({ provider: ProviderSchema.optional() });" }], focusPath: "src/provider.ts", expectedCount: 0, public: true },
    { id: "duplicate-provider", title: "Do not repeat one enum domain", outcome: "match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']) }); const StatusSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });" }], focusPath: "src/provider.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

function literalDomain(node: TSESTree.CallExpression): readonly string[] | null {
  const [argument] = node.arguments;
  if (argument?.type !== AST_NODE_TYPES.ArrayExpression || argument.elements.length < 2) return null;
  const values: string[] = [];
  for (const element of argument.elements) {
    if (element?.type !== AST_NODE_TYPES.Literal || typeof element.value !== "string") return null;
    values.push(element.value);
  }
  return values;
}

export default createRule<Options, MessageIds>({
  name: "prefer-shared-zod-enum",
  documentation: PREFER_SHARED_ZOD_ENUM_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Reuse identical literal Zod enum domains within a module." },
    schema: [],
    messages: {
      shareEnumDomain: "This Zod enum repeats an earlier identical domain; extract and reuse one module-level named schema.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const zodBindings = new Set<string>();
    const seen = new Set<string>();
    return {
      ImportDeclaration(node): void {
        if (!isZodModule(node.source.value)) return;
        for (const specifier of node.specifiers) {
          if (
            specifier.type === AST_NODE_TYPES.ImportNamespaceSpecifier ||
            specifier.type === AST_NODE_TYPES.ImportDefaultSpecifier ||
            (specifier.type === AST_NODE_TYPES.ImportSpecifier &&
              specifier.imported.type === AST_NODE_TYPES.Identifier &&
              specifier.imported.name === "z")
          ) zodBindings.add(specifier.local.name);
        }
      },
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          node.callee.computed ||
          node.callee.object.type !== AST_NODE_TYPES.Identifier ||
          !zodBindings.has(node.callee.object.name) ||
          node.callee.property.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.name !== "enum"
        ) return;
        const domain = literalDomain(node);
        if (domain === null) return;
        const key = JSON.stringify(domain);
        if (seen.has(key)) context.report({ node, messageId: "shareEnumDomain" });
        else seen.add(key);
      },
    };
  },
});
