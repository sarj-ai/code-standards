/**
 * @fileoverview _successful-parse-read — prove a successful parser result dominates a payload read.
 */
import {
  AST_NODE_TYPES,
  ASTUtils,
  type TSESTree,
} from "@typescript-eslint/utils";

import { unwrapExpression } from "./_unwrap-expression.js";

type ParseOrigin = (node: TSESTree.Node) => TSESTree.CallExpression | null;

/** Only explicit branches and same-function return/throw guards establish success. */
export function successfulParseRead(
  read: TSESTree.Node,
  call: TSESTree.CallExpression,
  origin: ParseOrigin,
): boolean {
  for (let current = read; current.parent != null; current = current.parent) {
    const parent = current.parent;
    if (
      parent.type === AST_NODE_TYPES.ArrowFunctionExpression ||
      parent.type === AST_NODE_TYPES.FunctionExpression ||
      parent.type === AST_NODE_TYPES.FunctionDeclaration
    )
      return false;
    if (
      successfulBranch(parent, current, call, origin) ||
      successfulGuardBefore(parent, current, call, origin)
    )
      return true;
  }
  return false;
}

function successfulBranch(
  parent: TSESTree.Node,
  read: TSESTree.Node,
  call: TSESTree.CallExpression,
  origin: ParseOrigin,
): boolean {
  if (
    parent.type !== AST_NODE_TYPES.IfStatement &&
    parent.type !== AST_NODE_TYPES.ConditionalExpression
  )
    return false;
  const polarity = successPolarity(parent.test, call, origin);
  return (
    (polarity === true && parent.consequent === read) ||
    (polarity === false && parent.alternate === read)
  );
}

function successfulGuardBefore(
  parent: TSESTree.Node,
  read: TSESTree.Node,
  call: TSESTree.CallExpression,
  origin: ParseOrigin,
): boolean {
  if (parent.type !== AST_NODE_TYPES.BlockStatement) return false;
  const position = parent.body.findIndex((statement) => statement === read);
  if (position < 0) return false;
  return parent.body.slice(0, position).some((statement) => {
    if (statement.type !== AST_NODE_TYPES.IfStatement) return false;
    const polarity = successPolarity(statement.test, call, origin);
    return (
      (polarity === false && abrupt(statement.consequent)) ||
      (polarity === true && abrupt(statement.alternate))
    );
  });
}

function successPolarity(
  node: TSESTree.Node,
  call: TSESTree.CallExpression,
  origin: ParseOrigin,
): boolean | null {
  node = unwrapExpression(node);
  if (node.type === AST_NODE_TYPES.UnaryExpression && node.operator === "!") {
    const value = successPolarity(node.argument, call, origin);
    return value === null ? null : !value;
  }
  if (
    node.type === AST_NODE_TYPES.MemberExpression &&
    ASTUtils.getPropertyName(node) === "success" &&
    origin(node.object) === call
  )
    return true;
  if (
    node.type !== AST_NODE_TYPES.BinaryExpression ||
    !["===", "!=="].includes(node.operator)
  )
    return null;
  const left = unwrapExpression(node.left);
  const right = unwrapExpression(node.right);
  const literal =
    right.type === AST_NODE_TYPES.Literal
      ? right
      : left.type === AST_NODE_TYPES.Literal
        ? left
        : null;
  if (literal?.value !== true && literal?.value !== false) return null;
  const value = successPolarity(literal === right ? left : right, call, origin);
  if (value === null) return null;
  const equal = value === literal.value;
  return node.operator === "===" ? equal : !equal;
}

function abrupt(node: TSESTree.Statement | null): boolean {
  if (node === null) return false;
  if (
    node.type === AST_NODE_TYPES.ReturnStatement ||
    node.type === AST_NODE_TYPES.ThrowStatement
  )
    return true;
  if (node.type !== AST_NODE_TYPES.BlockStatement) return false;
  const last = node.body.at(-1);
  return last !== undefined && abrupt(last);
}
