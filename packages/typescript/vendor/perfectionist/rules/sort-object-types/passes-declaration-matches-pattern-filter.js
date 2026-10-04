import { objectTypeParentTypes } from './types.js'
import { matchesScopedExpressions } from '../../utils/scoped-regex/matches-scoped-expressions.js'
import { computeNodeParentName } from './compute-node-parent-name.js'
/**
 * Checks whether the parent node's name matches the given pattern.
 *
 * @param params - The parameters object.
 * @param params.declarationMatchesPattern - The regex pattern to match against.
 * @param params.parentNodes - The parent nodes to check.
 * @param params.sourceCode - The source code object.
 * @returns True if the parent node's name passes the pattern filter, false
 *   otherwise.
 */
function passesDeclarationMatchesPatternFilter({
  declarationMatchesPattern,
  parentNodes,
  sourceCode,
}) {
  return matchesScopedExpressions({
    nodeValuesComputer: buildNodeValuesComputer(sourceCode),
    allowedNodeTypes: new Set(objectTypeParentTypes),
    scopedRegexOption: declarationMatchesPattern,
    parentNodes,
  })
}
function buildNodeValuesComputer(sourceCode) {
  return node => [computeNodeParentName(node, sourceCode)]
}
export { passesDeclarationMatchesPatternFilter }
