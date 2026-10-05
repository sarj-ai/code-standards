import { makeNewlinesBetweenFixes } from './make-newlines-between-fixes.js'
import { makeCommentAfterFixes } from './make-comment-after-fixes.js'
import { makeCommentAboveFixes } from './make-comment-above-fixes.js'
import { makeOrderFixes } from './make-order-fixes.js'
/**
 * Orchestrates the generation of all necessary fixes for sorting operations.
 *
 * Coordinates different types of fixes in a specific priority order to ensure
 * proper code transformation:
 *
 * 1. Order fixes - Reorders the nodes themselves
 * 2. Comment-after fixes - Handles inline trailing comments (if needed)
 * 3. Newlines fixes - Adjusts spacing between groups (if configured)
 * 4. Comment-above fixes - Adds/removes separator comments (if only these are
 *    needed).
 *
 * The function returns early when higher-priority fixes are found, as applying
 * multiple fix types simultaneously could cause conflicts. This ensures that
 * each auto-fix operation focuses on one type of change at a time.
 *
 * Notes:
 *
 * - Order fixes replace node ranges; comment-after/newlines operate on inter-node
 *   ranges. They are designed not to overlap, but if ESLint discards
 *   overlapping replacements, a subsequent lint pass will apply the remaining
 *   fixes.
 * - Comment-above fixes are not combined with other fix types to avoid noisy
 *   changes; they are applied only when nothing else is pending.
 *
 * @example
 *
 * ```ts
 * // Configuration with groups and newlines
 * const fixes = makeFixes({
 *   nodes: originalNodes,
 *   sortedNodes: sortedNodes,
 *   options: {
 *     groups: ['imports', 'types', 'functions'],
 *     newlinesBetween: 1,
 *   },
 *   sourceCode,
 *   fixer,
 *   hasCommentAboveMissing: false,
 * })
 * // Returns order fixes if nodes need reordering
 * // Otherwise returns newlines fixes if spacing needs adjustment
 * // Otherwise returns empty array
 * ```
 *
 * @template T - Type of sorting node.
 * @param params - Parameters for generating fixes.
 * @returns Array of ESLint fix operations to apply, prioritized by type.
 */
function makeFixes({
  ignoreFirstNodeHighestBlockComment,
  newlinesBetweenValueGetter,
  hasCommentAboveMissing,
  sortedNodes,
  sourceCode,
  options,
  fixer,
  nodes,
}) {
  let orderFixes = makeOrderFixes({
    ignoreFirstNodeHighestBlockComment,
    sortedNodes,
    sourceCode,
    options,
    nodes,
    fixer,
  })
  let commentAfterFixes = makeCommentAfterFixes({
    sortedNodes,
    sourceCode,
    nodes,
    fixer,
  })
  if (commentAfterFixes.length > 0) {
    return [...orderFixes, ...commentAfterFixes]
  }
  if (options?.groups) {
    let newlinesFixes = makeNewlinesBetweenFixes({
      options: {
        ...options,
        newlinesBetween: options.newlinesBetween,
        groups: options.groups,
      },
      newlinesBetweenValueGetter,
      sortedNodes,
      sourceCode,
      fixer,
      nodes,
    })
    if (newlinesFixes.length > 0) {
      return [...orderFixes, ...newlinesFixes]
    }
  }
  if (orderFixes.length > 0) {
    return orderFixes
  }
  if (!hasCommentAboveMissing || !options?.groups) {
    return []
  }
  return makeCommentAboveFixes({
    options: {
      ...options,
      groups: options.groups,
    },
    sortedNodes,
    sourceCode,
    fixer,
  })
}
export { makeFixes }
