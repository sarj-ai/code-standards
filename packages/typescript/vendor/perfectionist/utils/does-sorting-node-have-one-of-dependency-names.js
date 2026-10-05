/**
 * Checks whether the given sorting node has at least one of the given
 * dependency names.
 *
 * @param sortingNode - The sorting node to check.
 * @param dependencyNames - The dependency names to look for.
 * @returns True if the sorting node has at least one of the dependency names,
 *   false otherwise.
 */
function doesSortingNodeHaveOneOfDependencyNames(sortingNode, dependencyNames) {
  let sortingNodeDependencyNames = new Set(sortingNode.dependencyNames)
  return dependencyNames.some(dependencyName =>
    sortingNodeDependencyNames.has(dependencyName),
  )
}
export { doesSortingNodeHaveOneOfDependencyNames }
