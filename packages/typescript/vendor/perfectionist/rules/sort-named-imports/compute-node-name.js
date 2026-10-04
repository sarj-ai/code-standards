import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name of an import specifier node.
 *
 * @param node - The import specifier node.
 * @param ignoreAlias - Whether to ignore the alias and use the local name.
 * @returns The computed name of the import specifier.
 */
function computeNodeName(node, ignoreAlias) {
  if (!ignoreAlias) {
    return node.local.name
  }
  switch (node.imported.type) {
    case AST_NODE_TYPES.Identifier:
      return node.imported.name
    case AST_NODE_TYPES.Literal:
      return node.imported.value
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node.imported)
  }
}
export { computeNodeName }
