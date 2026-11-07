/**
 * @fileoverview _successful-parse-read — prove a successful parser result dominates a payload read.
 */

import type { ESTree, Node } from "../types.js";
import { parentOf, unwrapExpression } from "../utils/ast.js";
import { getPropertyName } from "../utils/static-string.js";

type ParseOrigin = (node: Node) => ESTree.CallExpression | null;

/** Only explicit branches and same-function return/throw guards establish success. */
export function successfulParseRead(read: Node, call: ESTree.CallExpression, origin: ParseOrigin): boolean {
  for (let current = read, parent = parentOf(current); parent !== null; current = parent, parent = parentOf(current)) {
    if (
      parent.type === "ArrowFunctionExpression" ||
      parent.type === "FunctionExpression" ||
      parent.type === "FunctionDeclaration"
    ) return false;
    if (successfulBranch(parent, current, call, origin) || successfulGuardBefore(parent, current, call, origin)) return true;
  }
  return false;
}

function successfulBranch(parent: Node, read: Node, call: ESTree.CallExpression, origin: ParseOrigin): boolean {
  if (parent.type !== "IfStatement" && parent.type !== "ConditionalExpression") return false;
  const polarity = successPolarity(parent.test, call, origin);
  return (polarity === true && parent.consequent === read) || (polarity === false && parent.alternate === read);
}

function successfulGuardBefore(parent: Node, read: Node, call: ESTree.CallExpression, origin: ParseOrigin): boolean {
  if (parent.type !== "BlockStatement") return false;
  const body = parent.body as readonly Node[];
  const position = body.findIndex((statement) => statement === read);
  if (position < 0) return false;
  return body.slice(0, position).some((statement) => {
    if (statement.type !== "IfStatement") return false;
    const polarity = successPolarity(statement.test, call, origin);
    return (polarity === false && abrupt(statement.consequent)) || (polarity === true && abrupt(statement.alternate));
  });
}

function successPolarity(node: Node, call: ESTree.CallExpression, origin: ParseOrigin): boolean | null {
  node = unwrapExpression(node);
  if (node.type === "UnaryExpression" && node.operator === "!") {
    const value = successPolarity(node.argument, call, origin);
    return value === null ? null : !value;
  }
  if (node.type === "MemberExpression" && getPropertyName(node) === "success" && origin(node.object) === call) return true;
  return node.type === "BinaryExpression" ? comparisonPolarity(node, call, origin) : null;
}

/** `result.success === true`, `false !== result.success` and the like. */
function comparisonPolarity(node: ESTree.BinaryExpression | ESTree.PrivateInExpression, call: ESTree.CallExpression, origin: ParseOrigin): boolean | null {
  if (node.operator !== "===" && node.operator !== "!==") return null;
  const left = unwrapExpression(node.left);
  const right = unwrapExpression(node.right);
  const literal = right.type === "Literal" ? right : left.type === "Literal" ? left : null;
  if (literal?.value !== true && literal?.value !== false) return null;
  const value = successPolarity(literal === right ? left : right, call, origin);
  if (value === null) return null;
  const equal = value === literal.value;
  return node.operator === "===" ? equal : !equal;
}

function abrupt(node: Node | null): boolean {
  if (node === null) return false;
  if (node.type === "ReturnStatement" || node.type === "ThrowStatement") return true;
  if (node.type !== "BlockStatement") return false;
  const last = (node.body as readonly Node[]).at(-1);
  return last !== undefined && abrupt(last);
}
