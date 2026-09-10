/**
 * @fileoverview prefer-shared-zod-enum — repeated literal enum domains can drift within one module.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-shared-zod-enum.test.ts
 */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isTestFile } from "./_paths.js";
import { isZodModule } from "./_zod.js";

type MessageIds = "shareEnumDomain";
type Options = [];

export const PREFER_SHARED_ZOD_ENUM_DOCUMENTATION = {
  summary: "Give repeated literal Zod enum domains one reusable module-level schema.",
  rationale: "Repeated literal domains hide a shared contract and allow equivalent fields to drift independently.",
  remediation: "Declare a module-level named Zod enum schema and reuse it at each field or contract site.",
  category: "maintainability",
  limitations: ["Only two or more exact, same-order direct z.enum calls with string-literal arrays and no customization argument in one module are inspected; one-off, computed, and customized domains require review. Equal values do not prove a shared business domain: retain local schemas when ownership or future evolution differs, and review initialization order before extraction."],
  examples: [
    { id: "shared-provider", title: "Reuse a named enum schema", outcome: "no-match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const ProviderSchema = z.enum(['agy', 'claude', 'sol']); const JobSchema = z.object({ provider: ProviderSchema }); const StatusSchema = z.object({ provider: ProviderSchema.optional() });" }], focusPath: "src/provider.ts", expectedCount: 0, public: true },
    { id: "inline-provider", title: "Do not repeat an inline enum domain", outcome: "match", files: [{ path: "src/provider.ts", source: "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']) }); const StatusSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });" }], focusPath: "src/provider.ts", expectedCount: 2, public: true },
  ],
} as const satisfies RuleDocumentation;

function literalDomain(node: TSESTree.CallExpression): readonly string[] | null {
  if (node.arguments.length !== 1) return null;
  const [argument] = node.arguments;
  if (argument?.type !== AST_NODE_TYPES.ArrayExpression || argument.elements.length < 2) return null;
  const values: string[] = [];
  for (const element of argument.elements) {
    if (element?.type !== AST_NODE_TYPES.Literal || typeof element.value !== "string") return null;
    values.push(element.value);
  }
  return values;
}

function isModuleLevelNamedSchema(node: TSESTree.CallExpression): boolean {
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
  const declarator = current.parent;
  if (
    declarator?.type !== AST_NODE_TYPES.VariableDeclarator ||
    declarator.init !== current ||
    declarator.id.type !== AST_NODE_TYPES.Identifier ||
    declarator.parent.type !== AST_NODE_TYPES.VariableDeclaration
  ) return false;
  const declarationParent = declarator.parent.parent;
  return (
    declarationParent.type === AST_NODE_TYPES.Program ||
    (declarationParent.type === AST_NODE_TYPES.ExportNamedDeclaration &&
      declarationParent.parent.type === AST_NODE_TYPES.Program)
  );
}

export default createRule<Options, MessageIds>({
  name: "prefer-shared-zod-enum",
  documentation: PREFER_SHARED_ZOD_ENUM_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: PREFER_SHARED_ZOD_ENUM_DOCUMENTATION.summary },
    schema: [],
    messages: {
      shareEnumDomain: "Extract this literal Zod enum to one module-level named schema and reuse it.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isGeneratedFile(context.filename, context.sourceCode.text)) return {};
    const zodBindings = new Set<TSESLint.Scope.Variable>();
    const bindingOf = (node: TSESTree.Identifier): TSESLint.Scope.Variable | null =>
      ASTUtils.findVariable(context.sourceCode.getScope(node), node.name);
    const candidates = new Map<string, Array<{ readonly node: TSESTree.CallExpression; readonly named: boolean }>>();
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
          ) {
            const binding = bindingOf(specifier.local);
            if (binding !== null) zodBindings.add(binding);
          }
        }
      },
      CallExpression(node): void {
        if (
          node.callee.type !== AST_NODE_TYPES.MemberExpression ||
          node.callee.computed ||
          node.callee.object.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.type !== AST_NODE_TYPES.Identifier ||
          node.callee.property.name !== "enum"
        ) return;
        const binding = bindingOf(node.callee.object);
        if (binding === null || !zodBindings.has(binding)) return;
        const domain = literalDomain(node);
        if (domain === null) return;
        const key = JSON.stringify(domain);
        const group = candidates.get(key) ?? [];
        group.push({ node, named: isModuleLevelNamedSchema(node) });
        candidates.set(key, group);
      },
      "Program:exit"(): void {
        for (const group of candidates.values()) {
          if (group.length < 2) continue;
          const canonical = group.find((candidate) => candidate.named);
          for (const candidate of group) {
            if (candidate === canonical) continue;
            context.report({ node: candidate.node, messageId: "shareEnumDomain" });
          }
        }
      },
    };
  },
});
