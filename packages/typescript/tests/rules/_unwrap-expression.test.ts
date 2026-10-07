// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { describe, expect, it } from "vitest";

import { unwrapExpression } from "../../src/rules/_unwrap-expression.js";

function expression(source: string): TSESTree.Expression {
  const statement = tsParser.parse(source).body[0];
  if (statement?.type !== AST_NODE_TYPES.ExpressionStatement) throw new Error("Expected expression");
  return statement.expression;
}

describe("unwrapExpression", () => {
  it.each([
    "value as unknown",
    "value satisfies unknown",
    "value!",
    "<unknown>value",
    "((value as unknown)! satisfies unknown)",
  ])("removes only erased wrappers from %s", (source) => {
    const value = unwrapExpression(expression(source));
    expect(value).toMatchObject({ type: AST_NODE_TYPES.Identifier, name: "value" });
    expect(unwrapExpression(value)).toBe(value);
  });

  it.each(["value?.member", "await value", "!value", "value()", "value.member"])(
    "preserves the identity of runtime expression %s",
    (source) => {
      const value = expression(source);
      expect(unwrapExpression(value)).toBe(value);
    },
  );
});
