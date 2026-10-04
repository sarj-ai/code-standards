/**
 * Populate sorting node groups based on the dependencies matrix.
 *
 * @param params - The parameters object.
 * @param params.dependenciesBySortingNode - A map of sorting nodes to their
 *   dependencies.
 * @param params.sortingNodeGroups - An array of sorting node groups.
 * @returns An array of sorting node groups with their dependencies.
 */
function populateSortingNodeGroupsWithDependencies({
  dependenciesBySortingNode,
  sortingNodeGroups,
}) {
  return sortingNodeGroups.map(sortingNodes =>
    computeSortingNodeGroupWithDependencies({
      dependenciesBySortingNode,
      sortingNodes,
    }),
  )
}
function computeSortingNodeGroupWithDependencies({
  dependenciesBySortingNode,
  sortingNodes,
}) {
  return sortingNodes.map(computeSortingNodeWithDependencies)
  function computeSortingNodeWithDependencies(sortingNode) {
    return {
      ...sortingNode,
      dependencies: computeSortingNodeDependencies({
        dependenciesBySortingNode,
        sortingNode,
      }),
    }
  }
}
function computeSortingNodeDependencies({
  dependenciesBySortingNode,
  sortingNode,
}) {
  let dependencies = dependenciesBySortingNode.get(sortingNode)
  if (!dependencies) {
    return []
  }
  return dependencies.flatMap(({ dependencyNames }) => dependencyNames)
}
export { populateSortingNodeGroupsWithDependencies }
