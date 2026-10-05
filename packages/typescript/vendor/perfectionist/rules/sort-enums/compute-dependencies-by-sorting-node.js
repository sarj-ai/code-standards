import { computeDependenciesBySortingNode as computeDependenciesBySortingNode$1 } from '../../utils/compute-dependencies-by-sorting-node.js'
import { computeParentNodesWithTypes } from '../../utils/compute-parent-nodes-with-types.js'
import { doesSortingNodeHaveOneOfDependencyNames } from '../../utils/does-sorting-node-have-one-of-dependency-names.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
function computeDependenciesBySortingNode({
  sortingNodes,
  sourceCode,
  enumName,
}) {
  return computeDependenciesBySortingNode$1({
    additionalIdentifierDependenciesComputer:
      buildAdditionalIdentifierDependenciesComputer({
        sortingNodes,
        enumName,
      }),
    sortingNodes,
    sourceCode,
  })
}
function buildAdditionalIdentifierDependenciesComputer({
  sortingNodes,
  enumName,
}) {
  return ({ referencingSortingNode, reference }) => {
    if (reference.identifier.name !== enumName) {
      return []
    }
    let relatedIdentifiers = computeMemberExpressionIdentifiers(
      reference.identifier,
      referencingSortingNode,
    )
    return sortingNodes.filter(sortingNode =>
      doesSortingNodeHaveOneOfDependencyNames(sortingNode, relatedIdentifiers),
    )
  }
}
function computeMemberExpressionIdentifiers(
  identifier,
  referencingSortingNode,
) {
  return computeParentNodesWithTypes({
    allowedTypes: [AST_NODE_TYPES.MemberExpression],
    maxParent: referencingSortingNode.node,
    consecutiveOnly: true,
    node: identifier,
  })
    .map(node => computeMemberExpressionPropertyName(node.property))
    .filter(name => name !== null)
}
function computeMemberExpressionPropertyName(property) {
  if (property.type === AST_NODE_TYPES.Identifier) {
    return property.name
  }
  if (
    property.type === AST_NODE_TYPES.Literal &&
    typeof property.value === 'string'
  ) {
    return property.value
  }
  return null
}
export { computeDependenciesBySortingNode }
