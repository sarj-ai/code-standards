/**
 * Builds a map from nodes to their corresponding sorting nodes.
 *
 * @param sortingNodes - An array of sorting nodes.
 * @returns A map where each key is a node and the value is its sorting node.
 */
function buildSortingNodeByNodeMap(sortingNodes) {
  let sortingNodeByNode = /* @__PURE__ */ new Map()
  for (let sortingNode of sortingNodes) {
    sortingNodeByNode.set(sortingNode.node, sortingNode)
  }
  return sortingNodeByNode
}
export { buildSortingNodeByNodeMap }
