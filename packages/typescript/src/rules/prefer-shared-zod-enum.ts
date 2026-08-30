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
  summary: "Give literal Zod enum domains one reusable module-level schema.",
  rationale: "Inline or repeated literal domains hide a reusable contract and allow equivalent fields to drift independently.",
  remediation: "Declare a module-level named Zod enum schema and reuse it at each field or contract site.",
  category: "maintainability",
  limitations: ["Only direct z.enum calls with string-literal arrays are inspected; computed domains require review."],
  examples: [
    { id: "shared-provider", title: "Reuse a named enum schema", outcome: "no-match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const ProviderSchema = z.enum(['agy', 'claude', 'sol']); const JobSchema = z.object({ provider: ProviderSchema }); const StatusSchema = z.object({ provider: ProviderSchema.optional() });" }], focusPath: "src/provider.ts", expectedCount: 0, public: true },
    { id: "inline-provider", title: "Do not inline enum domains in object fields", outcome: "match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']) });" }], focusPath: "src/provider.ts", expectedCount: 1, public: true },
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

function isStandaloneSchema(node: TSESTree.CallExpression): boolean {
  let current: TSESTree.Node = node;
  while (
    current.parent?.type === AST_NODE_TYPES.MemberExpression &&
    current.parent.object === current
  ) {
    current = current.parent;
    if (
      current.parent?.type === AST_NODE_TYPES.CallExpression &&
      current.parent.callee === current
    ) current = current.parent;
  }
  return (
    (current.parent?.type === AST_NODE_TYPES.VariableDeclarator &&
      current.parent.init === current &&
      current.parent.id.type === AST_NODE_TYPES.Identifier) ||
    (current.parent?.type === AST_NODE_TYPES.ExpressionStatement &&
      current.parent.expression === current)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-shared-zod-enum",
  documentation: PREFER_SHARED_ZOD_ENUM_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: "Give literal Zod enum domains one reusable module-level schema." },
    schema: [],
    messages: {
      shareEnumDomain: "Extract this literal Zod enum to one module-level named schema and reuse it.",
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
        const inline = !isStandaloneSchema(node);
        if (inline || seen.has(key))
          context.report({ node, messageId: "shareEnumDomain" });
        else seen.add(key);
      },
    };
  },
});
