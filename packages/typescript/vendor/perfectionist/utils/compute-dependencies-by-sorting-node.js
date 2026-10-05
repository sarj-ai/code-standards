import { computeDeepScopeReferences } from './compute-deep-scope-references.js'
import { rangeContainsRange } from './range-contains-range.js'
/**
 * Compute the list of dependencies for each sorting node.
 *
 * @param params - The parameters object.
 * @param params.additionalIdentifierDependenciesComputer - A function to
 *   compute additional dependencies for an identifier.
 * @param params.shouldIgnoreSortingNodeComputer - A function to determine if a
 *   sorting node should be ignored.
 * @param params.shouldIgnoreIdentifierComputer - A function to determine if an
 *   identifier should be ignored.
 * @param params.sortingNodes - The sorting nodes to compute dependencies for.
 * @param params.sourceCode - The source code object.
 * @returns A map of sorting nodes to their dependencies.
 */
function computeDependenciesBySortingNode({
  additionalIdentifierDependenciesComputer,
  shouldIgnoreSortingNodeComputer,
  shouldIgnoreIdentifierComputer,
  sortingNodes,
  sourceCode,
}) {
  let returnValue = /* @__PURE__ */ new Map()
  let references = sortingNodes.flatMap(sortingNode =>
    computeDeepScopeReferences(sortingNode.node, sourceCode),
  )
  let uniqueReferences = new Set(references)
  for (let reference of uniqueReferences) {
    let { identifier, resolved } = reference
    if (!resolved) {
      continue
    }
    let referencingSortingNode = findSortingNodeContainingIdentifier(
      sortingNodes,
      identifier,
    )
    if (!referencingSortingNode) {
      continue
    }
    if (shouldIgnoreSortingNodeComputer?.(referencingSortingNode)) {
      continue
    }
    let referencedNodes = returnValue.get(referencingSortingNode) ?? []
    returnValue.set(referencingSortingNode, referencedNodes)
    referencedNodes.push(
      ...computeMainIdentifierDependencies({
        shouldIgnoreSortingNodeComputer,
        shouldIgnoreIdentifierComputer,
        referencingSortingNode,
        sortingNodes,
        identifier,
        resolved,
      }),
      ...(additionalIdentifierDependenciesComputer?.({
        referencingSortingNode,
        reference,
      }) ?? []),
    )
  }
  return returnValue
}
function computeMainIdentifierDependencies({
  shouldIgnoreSortingNodeComputer,
  shouldIgnoreIdentifierComputer,
  referencingSortingNode,
  sortingNodes,
  identifier,
  resolved,
}) {
  if (
    shouldIgnoreIdentifierComputer?.({
      referencingSortingNode,
      identifier,
    })
  ) {
    return []
  }
  let [firstIdentifier] = resolved.identifiers
  if (!firstIdentifier) {
    return []
  }
  let referencedSortingNode = findSortingNodeContainingIdentifier(
    sortingNodes,
    firstIdentifier,
  )
  if (!referencedSortingNode) {
    return []
  }
  if (shouldIgnoreSortingNodeComputer?.(referencedSortingNode)) {
    return []
  }
  if (referencedSortingNode === referencingSortingNode) {
    return []
  }
  return [referencedSortingNode]
}
function findSortingNodeContainingIdentifier(sortingNodes, identifier) {
  return sortingNodes.find(sortingNode =>
    rangeContainsRange(sortingNode.node.range, identifier.range),
  )
}
export { computeDependenciesBySortingNode }
