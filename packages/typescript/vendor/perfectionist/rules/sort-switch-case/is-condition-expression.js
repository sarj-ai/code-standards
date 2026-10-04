import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Checks if an expression is condition-shaped.
 *
 * Condition-shaped expressions are boolean literals, logical negations, binary
 * expressions and logical expressions. Switch statements built on such
 * expressions (e.g. `switch (true)`) encode their program logic in the case
 * order, so sorting them is unsafe.
 *
 * @param node - The expression AST node to check.
 * @returns True if the expression is condition-shaped.
 */
function isConditionExpression(node) {
  switch (node.type) {
    case AST_NODE_TYPES.LogicalExpression:
    case AST_NODE_TYPES.BinaryExpression:
      return true
    case AST_NODE_TYPES.UnaryExpression:
      return node.operator === '!'
    case AST_NODE_TYPES.Literal:
      return typeof node.value === 'boolean'
    default:
      return false
  }
}
export { isConditionExpression }
