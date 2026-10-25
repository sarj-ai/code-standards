/**
 * @fileoverview no-known-value-widening — retain evidence in local values.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-known-value-widening.test.ts
 */
import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import ts from "typescript";

import { retainsNamedTypeUses } from "./_type-binding.js";
import { createRule, type RuleDocumentation } from "./_docs.js";
import { isUnusedPrivateBinding } from "./_unused-private-binding.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_KNOWN_VALUE_WIDENING_DOCUMENTATION = {
  summary: "Preserve a known value's contract instead of widening a local binding to unknown, object, or an unknown-valued dictionary.",
  rationale: "Erasing a typed value's fields forces downstream code to rediscover the same contract through casts, reflection, or representation checks.",
  remediation: "Keep the inferred type, select the required domain fields, or use satisfies to check compatibility without erasing evidence.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Requires TypeScript type information. Only annotated local const bindings with identifier initializers are inspected; literals, calls, parameters, exported bindings, and type assertions are excluded.",
    "Only unknown, object, and index-only dictionaries with unknown values are rejected. Typed dynamic registries, finite-key records, empty accumulators, and unknown external input are preserved.",
    "Intentional type erasure at a real abstraction boundary needs a local suppression explaining that boundary. Automatic fixes remove the annotation only from an unused private binding in a module or block; referenced bindings retain their declared contract for manual review.",
  ],
  examples: [
    { id: "erased-tool", title: "A dictionary erases a known tool contract", outcome: "match", files: [{ path: "src/tool.ts", source: "type Tool = { name: string; enabled: boolean };\ndeclare const tool: Tool;\nconst fields: Record<string, unknown> = tool;" }], focusPath: "src/tool.ts", expectedCount: 1, public: true },
    { id: "retained-tool", title: "Retain the tool's fields", outcome: "no-match", files: [{ path: "src/tool.ts", source: "type Tool = { name: string; enabled: boolean };\ndeclare const tool: Tool;\nconst fields = tool;" }], focusPath: "src/tool.ts", expectedCount: 0, public: true },
    {
      id: "safe-autofix",
      title: "Apply the proven automatic correction",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; declare const tool: { name: string }; const fields: unknown = tool;" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; declare const tool: { name: string }; const fields = tool;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;

function erasesContract(type: ts.Type, checker: ts.TypeChecker): boolean {
  if ((type.flags & (ts.TypeFlags.Unknown | ts.TypeFlags.NonPrimitive)) !== 0) return true;
  const indexes = checker.getIndexInfosOfType(type);
  return indexes.length > 0 && checker.getPropertiesOfType(type).length === 0 &&
    indexes.every((index) => (index.type.flags & ts.TypeFlags.Unknown) !== 0);
}

function hasUnknownContract(type: ts.Type, checker: ts.TypeChecker): boolean {
  if (type.isUnionOrIntersection()) return type.types.some((part) => hasUnknownContract(part, checker));
  return (type.flags & (ts.TypeFlags.Any | ts.TypeFlags.Unknown | ts.TypeFlags.Never | ts.TypeFlags.TypeParameter | ts.TypeFlags.Conditional | ts.TypeFlags.IndexedAccess | ts.TypeFlags.Substitution)) !== 0 || erasesContract(type, checker);
}

export default createRule<[], "widening">({
  name: "no-known-value-widening",
  documentation: NO_KNOWN_VALUE_WIDENING_DOCUMENTATION,
  meta: {
    type: "suggestion",
    fixable: "code",
    docs: { description: NO_KNOWN_VALUE_WIDENING_DOCUMENTATION.summary },
    schema: [],
    messages: { widening: "This annotation erases a known value's contract. Retain inference or use a domain contract instead of rediscovering fields through casts or runtime checks." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text)) return {};
    if (!context.sourceCode.parserServices?.program || !context.sourceCode.parserServices.esTreeNodeToTSNodeMap) return {};
    const services = ESLintUtils.getParserServices(context);
    if (services.program === null) return {};
    const checker = services.program.getTypeChecker();
    return {
      VariableDeclarator(node: TSESTree.VariableDeclarator): void {
        if (node.id.type !== AST_NODE_TYPES.Identifier || !node.id.typeAnnotation ||
          node.init?.type !== AST_NODE_TYPES.Identifier ||
          node.parent.kind !== "const" || node.parent.parent.type === AST_NODE_TYPES.ExportNamedDeclaration) return;
        const source = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.init));
        if (hasUnknownContract(source, checker)) return;
        const target = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.id.typeAnnotation.typeAnnotation));
        if (erasesContract(target, checker)) {
          const annotation = node.id.typeAnnotation;
          const canFix = isUnusedPrivateBinding(context.sourceCode, node, node.id, context.filename) &&
            context.sourceCode.getCommentsInside(annotation).length === 0 &&
            retainsNamedTypeUses(context.sourceCode, annotation);
          context.report({
            node: annotation, messageId: "widening",
            fix: canFix ? (fixer) => fixer.replaceText(annotation, context.sourceCode.getText(annotation).replace(/[^\r\n]/gu, "")) : null,
          });
        }
      },
    };
  },
});
