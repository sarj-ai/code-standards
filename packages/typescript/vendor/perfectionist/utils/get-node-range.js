import { getEslintDisabledRules } from './get-eslint-disabled-rules.js'
import { getCommentsBefore } from './get-comments-before.js'
import { isPartitionComment } from './is-partition-comment.js'
import * as ASTUtils from '../../eslint-utils/index.mjs'
/**
 * Determines the complete range of a node including its associated comments.
 *
 * Calculates the full range that should be considered when moving or analyzing
 * a node. This includes:
 *
 * - The node itself
 * - Parentheses surrounding the node (if any)
 * - Preceding comments that "belong" to the node.
 *
 * The function intelligently determines which comments should be included by:
 *
 * - Including comments directly above the node (no empty lines between)
 * - Stopping at partition comments (used to separate sections)
 * - Stopping at ESLint disable/enable comments
 * - Optionally excluding the highest block comment (e.g., file headers).
 *
 * @example
 *
 * ```ts
 * // Source code:
 * // This comment belongs to the function
 * // So does this one
 * function foo() {}
 *
 * const range = getNodeRange({ node: functionNode, sourceCode })
 * // Returns range including both comments
 * ```
 *
 * @example
 *
 * ```ts
 * // Source code:
 * /* File header comment *\/
 * // Function comment
 * function bar() { }
 *
 * const range = getNodeRange({
 * node: functionNode,
 * sourceCode,
 * ignoreHighestBlockComment: true
 * });
 * // Returns range including line comment but not block comment
 * ```
 *
 * @param params - Parameters for range calculation.
 * @returns Tuple of [start, end] positions including relevant comments.
 */
function getNodeRange({
  ignoreHighestBlockComment,
  implicitDecorators,
  sourceCode,
  options,
  node,
}) {
  let start = node.range.at(0)
  let end = node.range.at(1)
  let decorators =
    implicitDecorators ?? ('decorators' in node ? node.decorators : [])
  if (decorators[0]) {
    start = Math.min(start, decorators[0].range[0])
    let decoratorTopCommentStart = computeHighestCommentStart({
      comments: getCommentsBefore({
        node: decorators[0],
        sourceCode,
      }),
      anchorLine: decorators[0].loc.start.line,
      ignoreHighestBlockComment,
      options,
    })
    if (decoratorTopCommentStart !== void 0) {
      start = Math.min(start, decoratorTopCommentStart)
    }
  }
  if (ASTUtils.isParenthesized(node, sourceCode)) {
    let bodyOpeningParen = sourceCode.getTokenBefore(
      node,
      ASTUtils.isOpeningParenToken,
    )
    let bodyClosingParen = sourceCode.getTokenAfter(
      node,
      ASTUtils.isClosingParenToken,
    )
    start = Math.min(start, bodyOpeningParen.range.at(0))
    end = bodyClosingParen.range.at(1)
  }
  let topCommentStart = computeHighestCommentStart({
    comments: getCommentsBefore({
      sourceCode,
      node,
    }),
    anchorLine: node.loc.start.line,
    ignoreHighestBlockComment,
    options,
  })
  if (topCommentStart !== void 0) {
    start = Math.min(start, topCommentStart)
  }
  return [start, end]
}
function computeHighestCommentStart({
  ignoreHighestBlockComment,
  anchorLine,
  comments,
  options,
}) {
  let highestBlockComment = comments.find(comment => comment.type === 'Block')
  let highestCommentStart
  for (let i = comments.length - 1; i >= 0; i--) {
    let comment = comments[i]
    if (ignoreHighestBlockComment && comment === highestBlockComment) {
      break
    }
    let eslintDisabledRules = getEslintDisabledRules(comment.value)
    if (
      isPartitionComment({
        partitionByComment: options?.partitionByComment ?? false,
        comment,
      }) ||
      eslintDisabledRules?.eslintDisableDirective === 'eslint-disable' ||
      eslintDisabledRules?.eslintDisableDirective === 'eslint-enable'
    ) {
      break
    }
    /**
     * Check for newlines between comments or between the first comment and the
     * node.
     */
    let previousCommentOrAnchorLine =
      i === comments.length - 1 ? anchorLine : comments[i + 1].loc.start.line
    if (comment.loc.end.line !== previousCommentOrAnchorLine - 1) {
      break
    }
    highestCommentStart = comment.range.at(0)
  }
  return highestCommentStart
}
export { getNodeRange }
