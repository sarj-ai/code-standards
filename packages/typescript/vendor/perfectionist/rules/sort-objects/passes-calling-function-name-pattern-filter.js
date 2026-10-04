import { matchesScopedExpressions } from '../../utils/scoped-regex/matches-scoped-expressions.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Checks if the object passes the calling function name pattern filter.
 *
 * @param params - Parameters.
 * @param params.callingFunctionNamePattern - The pattern to evaluate.
 * @param params.parentNodes - The parent nodes of the object.
 * @param params.sourceCode - The source code object.
 * @returns True if the object passes the filter, false otherwise.
 */
function passesCallingFunctionNamePatternFilter({
  callingFunctionNamePattern,
  parentNodes,
  sourceCode,
}) {
  return matchesScopedExpressions({
    allowedNodeTypes: /* @__PURE__ */ new Set([AST_NODE_TYPES.CallExpression]),
    nodeValuesComputer: buildNodeValuesComputer(sourceCode),
    scopedRegexOption: callingFunctionNamePattern,
    parentNodes,
  })
}
function buildNodeValuesComputer(sourceCode) {
  return node => [sourceCode.getText(node.callee)]
}
export { passesCallingFunctionNamePatternFilter }
