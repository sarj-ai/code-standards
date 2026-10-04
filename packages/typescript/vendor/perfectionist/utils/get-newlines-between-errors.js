import { getNewlinesBetweenOption } from './get-newlines-between-option.js'
import { getLinesBetween } from './get-lines-between.js'
/**
 * Checks if the newlines between two nodes match the required configuration.
 *
 * Validates the number of empty lines between two nodes against the expected
 * newlines based on their group indices and configuration. Generates
 * appropriate error messages when the actual newlines don't match the
 * requirement.
 *
 * The function returns no errors if:
 *
 * - The left node's group index is greater than the right's (wrong order)
 * - The nodes are in different partitions
 * - The newlines configuration is set to 'ignore'
 * - The actual newlines match the expected newlines.
 *
 * @example
 *
 * ```ts
 * // Configuration requires 1 newline between different groups
 * const errors = getNewlinesBetweenErrors({
 *   options: { newlinesBetween: 1, groups: ['imports', 'types'] },
 *   leftGroupIndex: 0, // imports group
 *   rightGroupIndex: 1, // types group
 *   left: importNode,
 *   right: typeNode,
 *   sourceCode,
 *   missedSpacingError: 'missedNewline',
 *   extraSpacingError: 'extraNewline',
 * })
 * // If no newline between nodes: Returns ['missedNewline']
 * // If 2+ newlines between nodes: Returns ['extraNewline']
 * // If exactly 1 newline: Returns []
 * ```
 *
 * @template MessageIds - Type of error message identifiers.
 * @template T - Type of the sorting node.
 * @param params - Parameters for newline checking.
 * @returns Array of error message IDs (empty if no errors).
 */
function getNewlinesBetweenErrors({
  newlinesBetweenValueGetter,
  missedSpacingError,
  extraSpacingError,
  rightGroupIndex,
  leftGroupIndex,
  sourceCode,
  options,
  right,
  left,
}) {
  if (
    leftGroupIndex > rightGroupIndex ||
    left.partitionId !== right.partitionId
  ) {
    return []
  }
  let newlinesBetween = getNewlinesBetweenOption({
    nextNodeGroupIndex: rightGroupIndex,
    nodeGroupIndex: leftGroupIndex,
    options,
  })
  newlinesBetween =
    newlinesBetweenValueGetter?.({
      computedNewlinesBetween: newlinesBetween,
      right,
      left,
    }) ?? newlinesBetween
  if (newlinesBetween === 'ignore') {
    return []
  }
  let numberOfEmptyLinesBetween = getLinesBetween(sourceCode, left, right)
  if (numberOfEmptyLinesBetween < newlinesBetween) {
    return [missedSpacingError]
  }
  if (numberOfEmptyLinesBetween > newlinesBetween) {
    return [extraSpacingError]
  }
  return []
}
export { getNewlinesBetweenErrors }
