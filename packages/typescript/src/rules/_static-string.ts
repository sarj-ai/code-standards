/** @fileoverview _static-string — static values exclude interpolation and opaque expressions. */
import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { unwrapExpression } from "./_unwrap-expression.js";

export function staticString(node: TSESTree.Node | undefined): string | null {
  if (node === undefined) return null;
  const value = unwrapExpression(node);
  if (value.type === AST_NODE_TYPES.Literal && typeof value.value === "string") return value.value;
  return value.type === AST_NODE_TYPES.TemplateLiteral && value.expressions.length === 0
    ? value.quasis[0]?.value.cooked ?? null : null;
}
