import { isGroupWithOverridesOption } from './is-group-with-overrides-option.js'
import { isNewlinesBetweenOption } from './is-newlines-between-option.js'
import { UnreachableCaseError } from './unreachable-case-error.js'
/**
 * Computes the name of a group based on the provided group object.
 *
 * @param group - The group object.
 * @returns A string if:
 *
 *   - The group is a string.
 *   - The group is a commentAbove option with a string group.
 */
function computeGroupName(group) {
  if (typeof group === 'string' || Array.isArray(group)) {
    return computeStringGroupName(group)
  }
  if (isGroupWithOverridesOption(group)) {
    return computeStringGroupName(group.group)
  }
  /* v8 ignore else -- @preserve Exhaustive guard for unsupported group option. */
  if (isNewlinesBetweenOption(group)) {
    return null
  }
  /* v8 ignore next -- @preserve Exhaustive guard for unsupported group option. */
  throw new UnreachableCaseError(group)
}
function computeStringGroupName(group) {
  if (typeof group === 'string') {
    return group
  }
  return null
}
export { computeGroupName }
