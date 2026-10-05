import { matches } from '../matches.js'
import { partitionPatternsByScope } from './partition-patterns-by-scope.js'
/**
 * Checks whether any of the parent nodes match the scoped regex patterns.
 *
 * @param params - The parameters object.
 * @param params.nodeValuesComputer - Function to compute the string values of a
 *   node to match against.
 * @param params.scopedRegexOption - The scoped regex option to match against.
 * @param params.allowedNodeTypes - The set of allowed node types to consider.
 * @param params.parentNodes - The parent nodes to check.
 * @returns True if any parent node matches the scoped regex patterns, false
 *   otherwise.
 */
function matchesScopedExpressions({
  nodeValuesComputer,
  scopedRegexOption,
  allowedNodeTypes,
  parentNodes,
}) {
  if (!scopedRegexOption) {
    return true
  }
  let { shallowScopePatterns, deepScopePatterns } =
    partitionPatternsByScope(scopedRegexOption)
  return (
    matchesShallowScopedExpressions({
      patterns: shallowScopePatterns,
      nodeValuesComputer,
      allowedNodeTypes,
      parentNodes,
    }) ||
    matchesDeepScopedExpressions({
      patterns: deepScopePatterns,
      nodeValuesComputer,
      allowedNodeTypes,
      parentNodes,
    })
  )
}
function matchesShallowScopedExpressions({
  nodeValuesComputer,
  allowedNodeTypes,
  parentNodes,
  patterns,
}) {
  let [firstParent] = parentNodes
  // v8 ignore if -- @preserve Unsure how we can reach that case
  if (!firstParent) {
    return false
  }
  if (!isNodeTypeAmong(firstParent, allowedNodeTypes)) {
    return false
  }
  return matchesParentExpression({
    parentNode: firstParent,
    nodeValuesComputer,
    patterns,
  })
}
function matchesDeepScopedExpressions({
  nodeValuesComputer,
  allowedNodeTypes,
  parentNodes,
  patterns,
}) {
  return parentNodes
    .filter(parent => isNodeTypeAmong(parent, allowedNodeTypes))
    .some(parentNode =>
      matchesParentExpression({
        nodeValuesComputer,
        parentNode,
        patterns,
      }),
    )
}
function matchesParentExpression({ nodeValuesComputer, parentNode, patterns }) {
  let nodeValues = nodeValuesComputer(parentNode)
  return patterns.some(nodeValueMatchesPattern)
  function nodeValueMatchesPattern(pattern) {
    return nodeValues.some(nodeValue => matches(nodeValue, pattern))
  }
}
function isNodeTypeAmong(node, types) {
  return types.has(node.type)
}
export { matchesScopedExpressions }
