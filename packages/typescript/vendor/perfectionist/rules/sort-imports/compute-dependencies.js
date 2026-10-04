import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the dependencies of an import-like AST node.
 *
 * @deprecated - To remove when experimental dependency detection is the only
 *   option.
 * @param node - The AST node representing an import-like declaration.
 * @returns The names of the dependencies.
 */
function computeDependencies(node) {
  switch (node.type) {
    case AST_NODE_TYPES.TSImportEqualsDeclaration:
      return computeImportEqualsDeclarationDependencies(node)
    case AST_NODE_TYPES.VariableDeclaration:
    case AST_NODE_TYPES.ImportDeclaration:
      return []
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node)
  }
}
function computeImportEqualsDeclarationDependencies(node) {
  switch (node.moduleReference.type) {
    case AST_NODE_TYPES.TSExternalModuleReference:
    case AST_NODE_TYPES.Identifier:
      return []
    case AST_NODE_TYPES.TSQualifiedName: {
      let qualifiedName = getQualifiedNameDependencyName(node.moduleReference)
      /* v8 ignore if -- @preserve Unsure how we can reach that case */
      if (!qualifiedName) {
        return []
      }
      return [qualifiedName]
    }
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node.moduleReference)
  }
}
function getQualifiedNameDependencyName(node) {
  let currentNode = node
  while (currentNode.type === AST_NODE_TYPES.TSQualifiedName) {
    currentNode = currentNode.left
  }
  switch (currentNode.type) {
    /* v8 ignore next -- @preserve Unsure how we can reach that case */
    case AST_NODE_TYPES.ThisExpression:
      return null
    case AST_NODE_TYPES.Identifier:
      return currentNode.name
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(currentNode)
  }
}
export { computeDependencies }
