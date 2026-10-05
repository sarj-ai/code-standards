import { isGroupWithOverridesOption } from './is-group-with-overrides-option.js'
import { getCommentsBefore } from './get-comments-before.js'
/**
 * Determines if a comment should exist above a node when transitioning between
 * groups.
 *
 * Checks if the group configuration requires a comment above nodes when they
 * are the first element of their group following a different group. This is
 * used to enforce comment separators between different sections of sorted
 * code.
 *
 * The function returns null if:
 *
 * - The left and right elements are in the same or reversed group order
 * - The group configuration doesn't require a comment above.
 *
 * @example
 *
 * ```ts
 * const result = getCommentAboveThatShouldExist({
 *   options: {
 *     groups: [
 *       'external',
 *       { commentAbove: 'Internal imports' },
 *       'internal',
 *     ],
 *   },
 *   leftGroupIndex: 0, // 'external' group
 *   rightGroupIndex: 2, // 'internal' group
 *   sortingNode: internalImportNode,
 *   sourceCode,
 * })
 * // Returns: { comment: 'Internal imports', exists: false }
 * ```
 *
 * @template T - Type of the sorting node.
 * @param params - Parameters for checking comment requirements.
 * @param params.options - Configuration with groups that may require comments.
 * @param params.leftGroupIndex - Index of the previous element's group.
 * @param params.rightGroupIndex - Index of the current element's group.
 * @param params.sortingNode - Node to check for required comments.
 * @param params.sourceCode - ESLint source code for accessing comments.
 * @returns Object with required comment text and existence status, or null if
 *   no comment required.
 */
function getCommentAboveThatShouldExist({
  rightGroupIndex,
  leftGroupIndex,
  sortingNode,
  sourceCode,
  options,
}) {
  if (leftGroupIndex !== null && leftGroupIndex >= rightGroupIndex) {
    return null
  }
  let rightGroup = options.groups[rightGroupIndex]
  if (!rightGroup || !isGroupWithOverridesOption(rightGroup)) {
    return null
  }
  let rightGroupCommentAbove = rightGroup.commentAbove
  if (!rightGroupCommentAbove) {
    return null
  }
  return {
    comment: rightGroupCommentAbove,
    exists: !!getCommentsBefore({
      node: sortingNode.node,
      sourceCode,
    }).find(comment => commentMatches(comment.value, rightGroupCommentAbove)),
  }
}
function commentMatches(comment, expected) {
  return comment.toLowerCase().includes(expected.toLowerCase().trim())
}
export { getCommentAboveThatShouldExist }
