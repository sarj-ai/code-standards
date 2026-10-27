/** @fileoverview _escaping-action-return — exclude visibly dead or finalizer-overridden action results. */

import { AST_NODE_TYPES, ASTUtils, type TSESLint, type TSESTree } from "@typescript-eslint/utils";

import { forEachAstChild } from "./_for-each-ast-child.js";

export function escapingActionReturn(node: TSESTree.ReturnStatement, owner: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  let child: TSESTree.Node = node;
  while (child.parent !== undefined && child.parent !== owner) {
    const parent: TSESTree.Node = child.parent;
    if (!reachableAncestor(child, parent, sourceCode)) return false;
    child = parent;
  }
  return true;
}

function reachableAncestor(child: TSESTree.Node, parent: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  switch (parent.type) {
    case AST_NODE_TYPES.IfStatement: {
      const truth = condition(parent.test, sourceCode);
      if (truth === null) return true;
      return parent.consequent === child ? truth : !truth;
    }
    case AST_NODE_TYPES.WhileStatement:
    case AST_NODE_TYPES.ForStatement:
      return parent.test === null || condition(parent.test, sourceCode) !== false;
    case AST_NODE_TYPES.ForInStatement:
    case AST_NODE_TYPES.ForOfStatement:
    case AST_NODE_TYPES.SwitchStatement:
      return false;
    case AST_NODE_TYPES.TryStatement:
      return parent.finalizer === null || parent.finalizer === child || !transfers(parent.finalizer, sourceCode);
    case AST_NODE_TYPES.BlockStatement:
      return reachableBlockChild(parent.body, child, sourceCode);
    default:
      return true;
  }
}

function condition(node: TSESTree.Expression, sourceCode: TSESLint.SourceCode): boolean | null {
  const value = ASTUtils.getStaticValue(node, sourceCode.getScope(node));
  return value === null ? null : Boolean(value.value);
}

function reachableBlockChild(statements: readonly TSESTree.Statement[], child: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  for (const statement of statements) {
    if (statement === child) return true;
    if (opaquePrefix(statement) || exits(statement, sourceCode)) return false;
  }
  return true;
}

function exits(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  if (node.type === AST_NODE_TYPES.ReturnStatement || node.type === AST_NODE_TYPES.ThrowStatement ||
    node.type === AST_NODE_TYPES.BreakStatement || node.type === AST_NODE_TYPES.ContinueStatement) return true;
  if (node.type === AST_NODE_TYPES.BlockStatement) return node.body.some((statement) => exits(statement, sourceCode));
  if (node.type !== AST_NODE_TYPES.IfStatement) return false;
  const truth = condition(node.test, sourceCode);
  if (truth === true) return exits(node.consequent, sourceCode);
  if (truth === false) return node.alternate !== null && exits(node.alternate, sourceCode);
  return node.alternate !== null && exits(node.consequent, sourceCode) && exits(node.alternate, sourceCode);
}

function opaquePrefix(node: TSESTree.Node): boolean {
  if (node.type === AST_NODE_TYPES.BlockStatement) return node.body.some(opaquePrefix);
  if (node.type === AST_NODE_TYPES.IfStatement) return opaquePrefix(node.consequent) || (node.alternate !== null && opaquePrefix(node.alternate));
  return node.type === AST_NODE_TYPES.TryStatement || node.type === AST_NODE_TYPES.SwitchStatement ||
    node.type === AST_NODE_TYPES.LabeledStatement || node.type === AST_NODE_TYPES.WithStatement ||
    node.type === AST_NODE_TYPES.ForStatement || node.type === AST_NODE_TYPES.ForInStatement ||
    node.type === AST_NODE_TYPES.ForOfStatement || node.type === AST_NODE_TYPES.WhileStatement || node.type === AST_NODE_TYPES.DoWhileStatement;
}

function transfers(node: TSESTree.Node, sourceCode: TSESLint.SourceCode): boolean {
  if (node.type === AST_NODE_TYPES.FunctionDeclaration || node.type === AST_NODE_TYPES.FunctionExpression || node.type === AST_NODE_TYPES.ArrowFunctionExpression) return false;
  if (node.type === AST_NODE_TYPES.ReturnStatement || node.type === AST_NODE_TYPES.ThrowStatement ||
    node.type === AST_NODE_TYPES.BreakStatement || node.type === AST_NODE_TYPES.ContinueStatement) return true;
  return forEachAstChild(node, sourceCode.visitorKeys, (child) => transfers(child, sourceCode));
}
