/**
 * Builds the AST listeners for the rule based on the provided node types,
 * context, and sorter function.
 *
 * @param params - The parameters object.
 * @param params.nodeTypes - The AST node types to listen for.
 * @param params.context - The rule context.
 * @param params.sorter - The function that sorts the nodes based on the
 *   provided parameters.
 * @returns An object containing the AST listeners for the specified node types.
 */
function buildAstListeners({ nodeTypes, context, sorter }) {
  let emptyMatchedAstSelectors = /* @__PURE__ */ new Set()
  let matchedAstSelectorsByNode = /* @__PURE__ */ new WeakMap()
  let allAstSelectorMatchers = [
    ...new Set(
      context.options
        .map(option => option.useConfigurationIf?.matchesAstSelector)
        .filter(matchesAstSelector => matchesAstSelector !== void 0),
    ),
  ].map(astSelector => [
    astSelector,
    buildMatchedAstSelectorsCollector({
      matchedAstSelectorsByNode,
      astSelector,
      nodeTypes,
    }),
  ])
  return {
    ...Object.fromEntries(allAstSelectorMatchers),
    ...Object.fromEntries(nodeTypes.map(buildNodeTypeExitListener)),
  }
  function buildNodeTypeExitListener(nodeType) {
    return [
      `${nodeType}:exit`,
      node =>
        sorter({
          matchedAstSelectors:
            matchedAstSelectorsByNode.get(node) ?? emptyMatchedAstSelectors,
          context,
          node,
        }),
    ]
  }
}
function buildMatchedAstSelectorsCollector({
  matchedAstSelectorsByNode,
  astSelector,
  nodeTypes,
}) {
  return collectMatchedAstSelectors
  function collectMatchedAstSelectors(node) {
    if (!isNodeOfType(node)) {
      return
    }
    let matchedAstSelectors = matchedAstSelectorsByNode.get(node)
    if (!matchedAstSelectors) {
      matchedAstSelectors = /* @__PURE__ */ new Set()
      matchedAstSelectorsByNode.set(node, matchedAstSelectors)
    }
    matchedAstSelectors.add(astSelector)
  }
  function isNodeOfType(node) {
    return nodeTypes.includes(node.type)
  }
}
export { buildAstListeners }
