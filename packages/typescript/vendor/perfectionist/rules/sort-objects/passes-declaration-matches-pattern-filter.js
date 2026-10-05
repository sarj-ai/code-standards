import { matchesScopedExpressions } from '../../utils/scoped-regex/matches-scoped-expressions.js'
import { computePropertyOrVariableDeclaratorName } from './compute-property-or-variable-declarator-name.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
let allowedTypes = [AST_NODE_TYPES.VariableDeclarator, AST_NODE_TYPES.Property]
/**
 * Checks whether the node parent names match the given pattern.
 *
 * @param params - The parameters object.
 * @param params.declarationMatchesPattern - The regex pattern to match against.
 * @param params.parentNodes - The parent nodes to check.
 * @param params.sourceCode - The source code object.
 * @returns True if the parent node parent names passes the pattern filter,
 *   false otherwise.
 */
function passesDeclarationMatchesPatternFilter({
  declarationMatchesPattern,
  parentNodes,
  sourceCode,
}) {
  return matchesScopedExpressions({
    nodeValuesComputer: buildNodeValuesComputer(sourceCode),
    scopedRegexOption: declarationMatchesPattern,
    allowedNodeTypes: new Set(allowedTypes),
    parentNodes,
  })
}
function buildNodeValuesComputer(sourceCode) {
  return node => [
    computePropertyOrVariableDeclaratorName({
      sourceCode,
      node,
    }),
  ]
}
export { passesDeclarationMatchesPatternFilter }
