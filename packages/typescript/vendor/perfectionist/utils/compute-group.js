import { computeGroupsNames } from './compute-groups-names.js'
/**
 * Determines which group an element belongs to based on custom and predefined
 * groups.
 *
 * The function checks groups in the following priority order:
 *
 * 1. Custom groups (if defined) - checked first, highest priority
 * 2. Predefined groups - checked as fallback
 * 3. Returns 'unknown' if no matching group is found.
 *
 * Only groups that exist in options.groups are considered valid.
 *
 * @example
 *
 * ```ts
 * const group = computeGroup({
 *   options: {
 *     groups: ['react', 'external', 'internal'],
 *     customGroups: [{ groupName: 'react', anyOf: ['react', 'react-*'] }],
 *   },
 *   customGroupMatcher: customGroup => customGroup.anyOf.includes('react'),
 *   predefinedGroups: ['external'],
 *   name: 'react-dom',
 * })
 * // Returns: 'react'
 * ```
 *
 * @template CustomGroupMatchOptions - Type of custom group match options.
 * @param params - Parameters for group computation.
 * @param params.options - Configuration with available groups and custom
 *   groups.
 * @param params.customGroupMatcher - Matcher function for custom groups.
 * @param params.predefinedGroups - Fallback predefined groups to check.
 * @returns The matched group name or 'unknown' if no group matches.
 */
function computeGroup({ customGroupMatcher, predefinedGroups, options }) {
  let groupsSet = new Set(computeGroupsNames(options.groups))
  return (
    computeFirstMatchingCustomGroupName(
      groupsSet,
      options.customGroups,
      customGroupMatcher,
    ) ??
    predefinedGroups.find(group => groupsSet.has(group)) ??
    'unknown'
  )
}
function computeFirstMatchingCustomGroupName(
  groupsSet,
  customGroups,
  customGroupMatcher,
) {
  for (let customGroup of customGroups) {
    if (
      customGroupMatcher(customGroup) &&
      groupsSet.has(customGroup.groupName)
    ) {
      return customGroup.groupName
    }
  }
  return null
}
export { computeGroup }
