import { computeIdentifierNameDetails } from '../compute-identifier-name-details.js'
import { AST_NODE_TYPES } from '../../../../ast-node-types/index.cjs'
/**
 * Computes the name details of a method or property node.
 *
 * @param node - The method or property node to compute the name for.
 * @param sourceCode - The ESLint source code object.
 * @returns An object containing the name, whether it has a private hash, and
 *   the name without the starting hash.
 */
function computeMethodOrPropertyNameDetails(node, sourceCode) {
  switch (node.key.type) {
    case AST_NODE_TYPES.PrivateIdentifier:
    case AST_NODE_TYPES.Identifier:
    case AST_NODE_TYPES.Literal:
      return computeIdentifierNameDetails(node.key)
    default:
      return {
        nameWithoutStartingHash: sourceCode.getText(node.key),
        name: sourceCode.getText(node.key),
        hasPrivateHash: false,
      }
  }
}
export { computeMethodOrPropertyNameDetails }
