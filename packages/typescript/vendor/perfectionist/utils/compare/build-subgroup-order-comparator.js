import { isGroupWithOverridesOption } from '../is-group-with-overrides-option.js'
import { isNewlinesBetweenOption } from '../is-newlines-between-option.js'
import { UnreachableCaseError } from '../unreachable-case-error.js'
import { computeOrderedValue } from './compute-ordered-value.js'
function buildSubgroupOrderComparator({ groups, order }) {
  return (a, b) => {
    let subgroupContainingA = computeSubgroupContainingNode(a, groups)
    let subgroupContainingB = computeSubgroupContainingNode(b, groups)
    if (
      !subgroupContainingA ||
      !subgroupContainingB ||
      subgroupContainingA !== subgroupContainingB
    ) {
      return 0
    }
    let result =
      subgroupContainingA.indexOf(a.group) -
      subgroupContainingB.indexOf(b.group)
    return computeOrderedValue(result, order)
  }
}
function computeSubgroupContainingNode(sortingNode, groups) {
  for (let group of groups) {
    if (isNewlinesBetweenOption(group)) {
      continue
    }
    if (typeof group === 'string' || Array.isArray(group)) {
      if (doesStringSubgroupContainsNode(sortingNode, group)) {
        return group
      }
      continue
    }
    /* v8 ignore else -- @preserve Exhaustive guard for unsupported group option. */
    if (isGroupWithOverridesOption(group)) {
      if (doesStringSubgroupContainsNode(sortingNode, group.group)) {
        return group.group
      }
      continue
    }
    /* v8 ignore next -- @preserve Exhaustive guard for unsupported group option. */
    throw new UnreachableCaseError(group)
  }
  return null
}
function doesStringSubgroupContainsNode(sortingNode, subgroup) {
  if (typeof subgroup === 'string') {
    return false
  }
  return subgroup.includes(sortingNode.group)
}
export { buildSubgroupOrderComparator }
