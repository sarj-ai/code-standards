import { computeDependenciesBySortingNode } from './compute-dependencies-by-sorting-node.js'
import { isNodeInsideDeferredFunction } from './is-node-inside-deferred-function.js'
function computeDependenciesOutsideDeferredFunctionsBySortingNode({
  ignoreCallbackDependenciesPatterns,
  sortingNodes,
  sourceCode,
}) {
  return computeDependenciesBySortingNode({
    shouldIgnoreIdentifierComputer: buildShouldIgnoreIdentifierComputer(),
    sortingNodes,
    sourceCode,
  })
  function buildShouldIgnoreIdentifierComputer() {
    return ({ referencingSortingNode, identifier }) =>
      isNodeInsideDeferredFunction({
        maxParent: referencingSortingNode.node,
        ignoreCallbackDependenciesPatterns,
        node: identifier,
      })
  }
}
export { computeDependenciesOutsideDeferredFunctionsBySortingNode }
