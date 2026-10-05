import { computeParentNodesWithTypes } from './compute-parent-nodes-with-types.js'
import { isNodeImmediatelyCalled } from './is-node-immediately-called.js'
import { matches } from './matches.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
/**
 * Checks whether a node sits inside a function body that is deferred.
 *
 * Used to distinguish between references that are evaluated immediately (like
 * IIFEs or synchronous callbacks) and those whose execution is delayed (like
 * assigned functions or explicitly ignored callback wrappers).
 *
 * @param params - The parameters object.
 * @param params.ignoreCallbackDependenciesPatterns - Optional regex pattern to
 *   explicitly treat matching callback wrappers as deferred.
 * @param params.maxParent - Maximum exclusive parent node to stop the search
 *   at.
 * @param params.node - The AST node whose enclosing functions are inspected.
 * @returns Whether the node lives inside a deferred function.
 */
function isNodeInsideDeferredFunction({
  ignoreCallbackDependenciesPatterns,
  maxParent,
  node,
}) {
  if (
    ignoreCallbackDependenciesPatterns &&
    matchesIgnoreCallbackDependencyPattern({
      ignoreCallbackDependenciesPatterns,
      maxParent,
      node,
    })
  ) {
    return true
  }
  return computeParentNodesWithTypes({
    allowedTypes: [
      AST_NODE_TYPES.FunctionExpression,
      AST_NODE_TYPES.ArrowFunctionExpression,
    ],
    consecutiveOnly: false,
    maxParent,
    node,
  }).some(isFunctionDeferred)
}
function matchesIgnoreCallbackDependencyPattern({
  ignoreCallbackDependenciesPatterns,
  maxParent,
  node,
}) {
  return computeParentNodesWithTypes({
    allowedTypes: [AST_NODE_TYPES.CallExpression],
    consecutiveOnly: false,
    maxParent,
    node,
  }).some(callExpressionMatchesCallbackDependencyPattern)
  function callExpressionMatchesCallbackDependencyPattern(callExpression) {
    return (
      'name' in callExpression.callee &&
      matches(callExpression.callee.name, ignoreCallbackDependenciesPatterns)
    )
  }
}
function isFunctionDeferred(functionNode) {
  let { parent } = functionNode
  if (isNodeImmediatelyCalled(functionNode)) {
    return false
  }
  return parent.type !== AST_NODE_TYPES.CallExpression
}
export { isNodeInsideDeferredFunction }
