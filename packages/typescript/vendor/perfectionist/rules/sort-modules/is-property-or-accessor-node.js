import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Checks whether a node is a PropertyDefinition or AccessorProperty.
 *
 * @param node - The AST node to check.
 * @returns True if the node is a PropertyDefinition or AccessorProperty, false
 *   otherwise.
 */
function isPropertyOrAccessorNode(node) {
  return (
    node.type === AST_NODE_TYPES.PropertyDefinition ||
    node.type === AST_NODE_TYPES.AccessorProperty
  )
}
export { isPropertyOrAccessorNode }
