import { computeGroupsNames } from '../../utils/compute-groups-names.js'
import { isStringGroupSideEffectOnlyGroup } from './is-string-group-side-effect-only-group.js'
/**
 * Checks if a group is a side-effect-only group.
 *
 * A side-effect-only group is one that contains no imports or exports, and is
 * typically used for modules that only execute code without exporting any
 * values.
 *
 * @param group - The group to check.
 * @returns True if the group is a side-effect-only group, false otherwise.
 */
function isSideEffectOnlyGroup(group) {
  if (!group) {
    return false
  }
  let groupNames = computeGroupsNames([group])
  if (groupNames.length === 0) {
    return false
  }
  return groupNames.every(isStringGroupSideEffectOnlyGroup)
}
export { isSideEffectOnlyGroup }
