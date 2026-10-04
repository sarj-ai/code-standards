import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name of an export specifier node.
 *
 * @param node - The export specifier node.
 * @param ignoreAlias - Whether to ignore the alias and use the local name.
 * @returns The computed name of the export specifier.
 */
function computeNodeName(node, ignoreAlias) {
  let identifierToCheck = ignoreAlias ? node.local : node.exported
  switch (identifierToCheck.type) {
    case AST_NODE_TYPES.Identifier:
      return identifierToCheck.name
    case AST_NODE_TYPES.Literal:
      return identifierToCheck.value
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(identifierToCheck)
  }
}
export { computeNodeName }
