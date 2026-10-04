import { getNodeRange } from './get-node-range.js'
import { isExpressionContinuationToken } from './is-expression-continuation-token.js'
import { doesNodeEndWithExpression } from './does-node-end-with-expression.js'
/**
 * Generates fixes for reordering nodes to their sorted positions.
 *
 * Creates text replacement fixes that swap node positions to achieve the
 * desired sort order. The function handles several important edge cases:
 *
 * - Preserves leading comments and documentation
 * - Maintains file-level block comments for the first node
 * - Adds safety semicolons when needed to prevent ASI issues
 * - Respects partition boundaries defined by comments.
 *
 * The function iterates through each node position and replaces the original
 * node text with the text from the node that should be in that position
 * according to the sorted order.
 *
 * @example
 *
 * ```ts
 * // Original order:
 * const b = 2
 * const a = 1
 *
 * // After applying order fixes:
 * const a = 1
 * const b = 2
 * ```
 *
 * @example
 *
 * ```ts
 * // Safety semicolon example
 * // Original:
 * const b = 2
 * const a = 1 // 'a' will move to first position
 *
 * // After fix (semicolon added to prevent ASI issues):
 * const a = 1
 * const b = 2
 * ```
 *
 * @param params - Parameters for generating order fixes.
 * @returns Array of ESLint fix operations to reorder nodes.
 */
function makeOrderFixes({
  ignoreFirstNodeHighestBlockComment,
  sortedNodes,
  sourceCode,
  options,
  fixer,
  nodes,
}) {
  let fixes = []
  for (let max = nodes.length, i = 0; i < max; i++) {
    let sortingNode = nodes.at(i)
    let sortedSortingNode = sortedNodes.at(i)
    let { implicitDecorators, node } = sortingNode
    let { addSafetySemicolonWhenInline, node: sortedNode } = sortedSortingNode
    let isNodeFirstNode = node === nodes.at(0).node
    let isSortedNodeFirstNode = sortedNode === nodes.at(0).node
    if (node === sortedNode) {
      continue
    }
    let sortedNodeCode = sourceCode.text.slice(
      ...getNodeRange({
        ignoreHighestBlockComment:
          ignoreFirstNodeHighestBlockComment && isSortedNodeFirstNode,
        implicitDecorators: sortedSortingNode.implicitDecorators,
        node: sortedNode,
        sourceCode,
        options,
      }),
    )
    let sortedNodeText = sourceCode.getText(sortedNode)
    let nextToken = sourceCode
      .getTokensAfter(node, {
        includeComments: false,
        count: 1,
      })
      .at(0)
    let sortedNextNodeEndsWithSafeCharacter =
      sortedNodeText.endsWith(';') || sortedNodeText.endsWith(',')
    let isNextTokenOnSameLineAsNode =
      nextToken?.loc.start.line === node.loc.end.line
    let isNextTokenSafeCharacter =
      nextToken?.value === ';' || nextToken?.value === ','
    let nextSortedSortingNode = sortedNodes.at(i + 1)
    let followingToken =
      nextSortedSortingNode ?
        sourceCode.getFirstToken(nextSortedSortingNode.node)
      : nextToken
    let isFollowedByExpressionContinuation =
      doesNodeEndWithExpression(sortedNode) &&
      isExpressionContinuationToken(followingToken)
    if (
      addSafetySemicolonWhenInline &&
      !sortedNextNodeEndsWithSafeCharacter &&
      !isNextTokenSafeCharacter &&
      (isNextTokenOnSameLineAsNode || isFollowedByExpressionContinuation)
    ) {
      sortedNodeCode += ';'
    }
    fixes.push(
      fixer.replaceTextRange(
        getNodeRange({
          ignoreHighestBlockComment:
            ignoreFirstNodeHighestBlockComment && isNodeFirstNode,
          implicitDecorators,
          sourceCode,
          options,
          node,
        }),
        sortedNodeCode,
      ),
    )
  }
  return fixes
}
export { makeOrderFixes }
