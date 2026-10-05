import { AST_NODE_TYPES } from '../../../../ast-node-types/index.cjs'
/**
 * Checks whether a node is a function expression or an arrow function
 * expression.
 *
 * @param node - The AST node to check.
 * @returns Whether the node is a function expression.
 */
function isFunctionExpression(node) {
  if (!node) {
    return false
  }
  return (
    node.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    node.type === AST_NODE_TYPES.FunctionExpression
  )
}
export { isFunctionExpression }
