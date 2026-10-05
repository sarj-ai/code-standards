import { isGroupWithOverridesOption } from './is-group-with-overrides-option.js'
import { isNewlinesBetweenOption } from './is-newlines-between-option.js'
import { UnreachableCaseError } from './unreachable-case-error.js'
/**
 * Computes the names of all groups based on the provided `GroupsOptions`.
 *
 * @param groups - An array of group options.
 * @returns An array of computed group names as strings.
 */
function computeGroupsNames(groups) {
  return groups.flatMap(group => computeGroupNames(group))
}
function computeGroupNames(group) {
  if (typeof group === 'string' || Array.isArray(group)) {
    return computeStringGroupNames(group)
  }
  if (isGroupWithOverridesOption(group)) {
    return computeStringGroupNames(group.group)
  }
  /* v8 ignore else -- @preserve Exhaustive guard for unsupported group option. */
  if (isNewlinesBetweenOption(group)) {
    return []
  }
  /* v8 ignore next -- @preserve Exhaustive guard for unsupported group option. */
  throw new UnreachableCaseError(group)
}
function computeStringGroupNames(group) {
  if (typeof group === 'string') {
    return [group]
  }
  return group
}
export { computeGroupsNames }
