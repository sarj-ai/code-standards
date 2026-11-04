/**
 * @fileoverview no-logical-or-fallback — distinguish missing values from empty strings and zero.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-logical-or-fallback.test.ts
 */

import { ASTUtils, AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { isBigIntLiteralType, isBooleanLiteralType } from "ts-api-utils";
import ts from "typescript";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { getTypeServices, type TypeServices, type TypeScriptSourceCode } from "./_eslint-rule.js";
import { isGeneratedFile } from "./_paths.js";
import { outerExpression, unwrapExpression } from "./_unwrap-expression.js";

const PRIMITIVE_FLAGS = ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BigIntLike | ts.TypeFlags.BooleanLike;
const GLOBAL_RECEIVERS: ReadonlySet<string> = new Set(["globalThis", "window", "self"]);

export const NO_LOGICAL_OR_FALLBACK_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Use nullish defaults or explicit falsy-value checks instead of logical OR fallbacks.",
  rationale: "Logical OR falls back for empty strings, zero and false as well as missing values. This hides which values should actually receive a default.",
  remediation: "Use ?? for null or undefined. If an empty string, zero or false needs special handling, test that condition explicitly and preserve the intended behavior.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Requires TypeScript type information and strict null checks. Reports non-nullable string, number or bigint value fallbacks, including branded primitives and mixed primitive unions. Nullable inputs, including nullable booleans, remain owned by @typescript-eslint/prefer-nullish-coalescing; both rules are enabled in the managed strict config.",
    "Preserves non-nullable boolean aggregation, conditions, negations, left-hand && guards, and calls to the native unshadowed Boolean constructor, including erased TypeScript wrappers and globalThis/window/self access. Constant truthiness stays with no-unnecessary-condition. Unknown, any, unresolved generic, object-only and generated inputs are excluded. Strings and comments are never scanned as code.",
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
        if (node.operator !== "||" || booleanContext(node, context.sourceCode, services)) return;
        const type = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(node.left));
        const members = (type.isUnion() ? type.types : [type]).map(primitivePart);
        if (members.some(member => member === undefined) ||
          !members.some(member => member !== undefined && (member.flags & (ts.TypeFlags.StringLike | ts.TypeFlags.NumberLike | ts.TypeFlags.BigIntLike)) !== 0)) return;
        const truthiness = members.map(member => member === undefined ? undefined : literalTruthiness(member));
        if (truthiness.every(value => value === true) || truthiness.every(value => value === false)) return;
        context.report({ node, messageId: "logicalOrFallback" });
      },
    };
  },
});

function primitivePart(type: ts.Type): ts.Type | undefined {
  if ((type.flags & PRIMITIVE_FLAGS) !== 0) return type;
  if (!type.isIntersection() || type.types.some(member => (member.flags & ts.TypeFlags.TypeParameter) !== 0)) return undefined;
  return type.types.find(member => (member.flags & PRIMITIVE_FLAGS) !== 0);
}

function literalTruthiness(type: ts.Type): boolean | undefined {
  if (type.isStringLiteral() || type.isNumberLiteral()) return Boolean(type.value);
  if (isBooleanLiteralType(type)) return type.intrinsicName === "true";
  if (isBigIntLiteralType(type)) return type.value.base10Value !== "0";
  return undefined;
}

function booleanContext(node: TSESTree.Node, source: TypeScriptSourceCode, services: TypeServices): boolean {
  let current = outerExpression(node);
  while (current.parent !== undefined) {
    const parent = current.parent;
    switch (parent.type) {
      case AST_NODE_TYPES.LogicalExpression:
        if (parent.operator === "&&" && parent.left === current) return true;
        current = outerExpression(parent);
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
        return parent.arguments[0] === current && nativeBoolean(parent.callee, source, services);
      default:
        return false;
    }
  }
  return false;
}

function nativeBoolean(node: TSESTree.Node, source: TypeScriptSourceCode, services: TypeServices): boolean {
  const callee = unwrapExpression(node);
  const checker = services.program.getTypeChecker();
  let symbol: ts.Symbol | undefined;
  if (callee.type === AST_NODE_TYPES.Identifier && callee.name === "Boolean" && !ASTUtils.findVariable(source.getScope(callee), callee.name)?.defs.length) {
    symbol = checker.getSymbolAtLocation(services.esTreeNodeToTSNodeMap.get(callee));
  } else if (callee.type === AST_NODE_TYPES.MemberExpression && ASTUtils.getPropertyName(callee) === "Boolean") {
    const receiver = unwrapExpression(callee.object);
    if (receiver.type !== AST_NODE_TYPES.Identifier || !GLOBAL_RECEIVERS.has(receiver.name) || ASTUtils.findVariable(source.getScope(receiver), receiver.name)?.defs.length) return false;
    symbol = checker.getTypeAtLocation(services.esTreeNodeToTSNodeMap.get(receiver)).getProperty("Boolean");
  }
  return symbol?.declarations !== undefined && symbol.declarations.length > 0 &&
    symbol.declarations.every(declaration => services.program.isSourceFileDefaultLibrary(declaration.getSourceFile()));
}
