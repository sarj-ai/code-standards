import { isPropertyOrAccessorNode } from './is-property-or-accessor-node.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Checks whether a node is a property or accessor node with an
 * ArrowFunctionExpression value.
 *
 * @param node - The AST node to check.
 * @returns True if the node is a property or accessor node with an
 *   ArrowFunctionExpression value, false otherwise.
 */
function isArrowFunctionNode(node) {
  return (
    isPropertyOrAccessorNode(node) &&
    node.value !== null &&
    node.value.type === AST_NODE_TYPES.ArrowFunctionExpression
  )
}
export { isArrowFunctionNode }
