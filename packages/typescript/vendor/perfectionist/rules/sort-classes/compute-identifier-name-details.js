import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name details of an identifier.
 *
 * @param node - The node to compute the name details for.
 * @returns An object containing the name, whether it has a private hash, and
 *   the name without the starting hash.
 */
function computeIdentifierNameDetails(node) {
  switch (node.type) {
    case AST_NODE_TYPES.PrivateIdentifier:
      return {
        nameWithoutStartingHash: node.name,
        name: `#${node.name}`,
        hasPrivateHash: true,
      }
    case AST_NODE_TYPES.Identifier:
      return buildNonPrivateHashDetails(node.name)
    case AST_NODE_TYPES.Literal:
      return buildNonPrivateHashDetails(String(node.value))
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node)
  }
}
function buildNonPrivateHashDetails(name) {
  return {
    nameWithoutStartingHash: name,
    hasPrivateHash: false,
    name,
  }
}
export { computeIdentifierNameDetails }
