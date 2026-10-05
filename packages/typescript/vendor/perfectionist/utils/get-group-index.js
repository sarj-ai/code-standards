import { isGroupWithOverridesOption } from './is-group-with-overrides-option.js'
import { isNewlinesBetweenOption } from './is-newlines-between-option.js'
import { UnreachableCaseError } from './unreachable-case-error.js'
/**
 * Determines the index of the group that a node belongs to.
 *
 * Searches through the groups array to find which group contains the node.
 * Supports simple groups (string), subgroups (array of strings) and objects
 * containing a `group` property. For subgroups, the node matches if its group
 * is any element in the array.
 *
 * The function returns the index of the matching group. If no group matches, it
 * returns the length of the groups array, which conventionally represents the
 * "unknown" group and ensures such nodes are sorted last.
 *
 * @example
 *
 * ```ts
 * const groups = ['imports', ['types', 'interfaces'], 'functions']
 * const node1 = { group: 'imports', name: 'lodash' }
 * const node2 = { group: 'types', name: 'User' }
 * const node3 = { group: 'unknown-group', name: 'misc' }
 *
 * getGroupIndex(groups, node1) // Returns: 0
 * getGroupIndex(groups, node2) // Returns: 1 (matches subgroup)
 * getGroupIndex(groups, node3) // Returns: 3 (groups.length, unknown group)
 * ```
 *
 * @param groups - Array of group configurations (strings or arrays of strings).
 * @param node - Sorting node with a group property to match.
 * @returns Index of the matching group, or groups.length if no match found.
 */
function getGroupIndex(groups, node) {
  for (let max = groups.length, i = 0; i < max; i++) {
    let currentGroup = groups[i]
    if (doesGroupMatch(currentGroup, node.group)) {
      return i
    }
  }
  return groups.length
}
function doesGroupMatch(group, groupName) {
  if (typeof group === 'string' || Array.isArray(group)) {
    return doesStringGroupMatch(group, groupName)
  }
  if (isGroupWithOverridesOption(group)) {
    return doesStringGroupMatch(group.group, groupName)
  }
  /* v8 ignore else -- @preserve Exhaustive guard: other directives are filtered out earlier. */
  if (isNewlinesBetweenOption(group)) {
    return false
  }
  /* v8 ignore next -- @preserve Exhaustive guard: other directives are filtered out earlier. */
  throw new UnreachableCaseError(group)
}
function doesStringGroupMatch(group, groupName) {
  if (typeof group === 'string') {
    return group === groupName
  }
  return group.includes(groupName)
}
export { getGroupIndex }
