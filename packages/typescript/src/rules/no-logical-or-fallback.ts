/**
 * @fileoverview no-logical-or-fallback — distinguish missing values from empty strings and zero.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-logical-or-fallback.test.ts
 */

import { ASTUtils, AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { isBigIntLiteralType, isBooleanLiteralType } from "ts-api-utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { getTypeServices, type TypeScriptSourceCode } from "./_eslint-rule.js";
import { isGeneratedFile } from "./_paths.js";

export const NO_LOGICAL_OR_FALLBACK_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Use nullish defaults or explicit falsy-value checks instead of logical OR fallbacks.",
  rationale: "Logical OR falls back for empty strings, zero and false as well as missing values. This hides which values should actually receive a default.",
  remediation: "Use ?? for null or undefined. If an empty string, zero or false needs special handling, test that condition explicitly and preserve the intended behavior.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Requires TypeScript type information and strict null checks. Reports non-nullable string, number or bigint value fallbacks, including mixed primitive unions. Nullable inputs remain owned by @typescript-eslint/prefer-nullish-coalescing; both rules are enabled in the managed strict config.",
    "Preserves boolean aggregation, conditions, negations, left-hand && guards, and calls to the unshadowed Boolean constructor. Constant truthiness stays with no-unnecessary-condition. Unknown, any, generic, object-only and generated inputs are excluded. Strings and comments are never scanned as code.",
    "No automatic replacement is offered: replacing || with ?? would change empty-string or zero behavior. Non-nullable ||= expressions remain outside this companion rule.",
  ],
  references: ["https://typescript-eslint.io/rules/prefer-nullish-coalescing/"],
  examples: [
    { id: "logical-or-title", title: "Do not hide empty-string fallback behavior", outcome: "match", files: [{ path: "src/title.ts", source: 'export function title(value: string) { return value.trim() || "Untitled"; }' }], focusPath: "src/title.ts", expectedCount: 1, public: true },
    { id: "explicit-empty-title", title: "Preserve an intentional empty-string default", outcome: "no-match", files: [{ path: "src/title.ts", source: 'export function title(value: string) { const trimmed = value.trim(); return trimmed === "" ? "Untitled" : trimmed; }' }], focusPath: "src/title.ts", expectedCount: 0, public: true },
    { id: "boolean-aggregation", title: "Keep boolean OR", outcome: "no-match", files: [{ path: "src/access.ts", source: 'export function allowed(isAdmin: boolean, isOwner: boolean) { return isAdmin || isOwner; }' }], focusPath: "src/access.ts", expectedCount: 0, public: false },
  ],
} as const satisfies RuleDocumentation;

export default createRule<[], "logicalOrFallback">({
  name: "no-logical-or-fallback",
  documentation: NO_LOGICAL_OR_FALLBACK_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_LOGICAL_OR_FALLBACK_DOCUMENTATION.summary },
    schema: [],
    messages: { logicalOrFallback: "Use ?? for a missing-value default. If an empty string, zero or false should trigger this fallback, test that condition explicitly; replacing || blindly changes behavior." },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context, context.sourceCode.text) || !context.sourceCode.parserServices?.program) return {};
    const services = getTypeServices(context);
    const checker = services.program.getTypeChecker();
    const options = services.program.getCompilerOptions();
    if (!(options.strictNullChecks ?? options.strict ?? false)) return {};
    return {
      LogicalExpression(node): void {
        if (node.operator !== "||" || booleanContext(node, context.sourceCode)) return;
        const type = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.left));
        const members = type.isUnion() ? type.types : [type];
        const primitiveFlags = ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BigIntLike | ts.TypeFlags.BooleanLike;
        if (!members.every(member => (member.flags & primitiveFlags) !== 0) ||
          !members.some(member => (member.flags & (ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BigIntLike)) !== 0)) return;
        const truthiness = members.map(literalTruthiness);
        if (truthiness.every(value => value === true) || truthiness.every(value => value === false)) return;
        context.report({ node, messageId: "logicalOrFallback" });
      },
    };
  },
});

function literalTruthiness(type: ts.Type): boolean | undefined {
  if (type.isStringLiteral() || type.isNumberLiteral()) return Boolean(type.value);
  if (isBooleanLiteralType(type)) return type.intrinsicName === "true";
  if (isBigIntLiteralType(type)) return type.value.base10Value !== "0";
  return undefined;
}

function booleanContext(node: TSESTree.Node, source: TypeScriptSourceCode): boolean {
  let current = node;
  while (current.parent !== undefined) {
    const parent = current.parent;
    switch (parent.type) {
      case AST_NODE_TYPES.TSAsExpression:
      case AST_NODE_TYPES.TSSatisfiesExpression:
      case AST_NODE_TYPES.TSNonNullExpression:
        current = parent;
        continue;
      case AST_NODE_TYPES.LogicalExpression:
        if (parent.operator === "&&" && parent.left === current) return true;
        current = parent;
        continue;
      case AST_NODE_TYPES.IfStatement:
      case AST_NODE_TYPES.WhileStatement:
      case AST_NODE_TYPES.DoWhileStatement:
      case AST_NODE_TYPES.ForStatement:
      case AST_NODE_TYPES.ConditionalExpression:
        return parent.test === current;
      case AST_NODE_TYPES.UnaryExpression:
        return parent.operator === "!";
      case AST_NODE_TYPES.CallExpression:
        return parent.callee.type === AST_NODE_TYPES.Identifier && parent.callee.name === "Boolean" &&
          parent.arguments[0] === current && ASTUtils.findVariable(source.getScope(parent.callee), "Boolean")?.defs.length === 0;
      default:
        return false;
    }
  }
  return false;
}
