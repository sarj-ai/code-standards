import { computeComparators } from './compare/compute-comparators.js'
/**
 * Core sorting function that performs the actual node sorting.
 *
 * This is the fundamental sorting engine of the Perfectionist plugin. It
 * handles the actual comparison and ordering of nodes while preserving the
 * positions of ignored elements. The function separates nodes into two
 * categories:
 *
 * 1. Nodes to be sorted (non-ignored)
 * 2. Nodes to keep in place (ignored or ESLint-disabled).
 *
 * After sorting, ignored nodes are reinserted at their original positions,
 * ensuring that intentionally placed elements remain untouched.
 *
 * @param params - Parameters for sorting operation.
 * @returns Sorted array with ignored nodes preserved at original positions.
 */
function sortNodes({
  comparatorByOptionsComputer,
  ignoreEslintDisabledNodes,
  isNodeIgnored,
  options,
  nodes,
}) {
  let nonIgnoredNodes = []
  let ignoredNodeIndices = []
  for (let [index, sortingNode] of nodes.entries()) {
    if (
      (ignoreEslintDisabledNodes && sortingNode.isEslintDisabled) ||
      isNodeIgnored?.(sortingNode)
    ) {
      ignoredNodeIndices.push(index)
    } else {
      nonIgnoredNodes.push(sortingNode)
    }
  }
  let comparators = computeComparators(comparatorByOptionsComputer, options)
  let sortedNodes = [...nonIgnoredNodes].toSorted((a, b) => {
    for (let comparator of comparators) {
      let result = comparator(a, b)
      if (result) {
        return result
      }
    }
    return 0
  })
  for (let ignoredIndex of ignoredNodeIndices) {
    sortedNodes.splice(ignoredIndex, 0, nodes[ignoredIndex])
  }
  return sortedNodes
}
export { sortNodes }
