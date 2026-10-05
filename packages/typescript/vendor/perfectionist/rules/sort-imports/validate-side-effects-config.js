import { computeGroupsNames } from '../../utils/compute-groups-names.js'
import { isStringGroupSideEffectOnlyGroup } from './is-string-group-side-effect-only-group.js'
import { isSideEffectOnlyGroup } from './is-side-effect-only-group.js'
/**
 * Validates that side-effect import groups are configured correctly.
 *
 * When sortSideEffects is false, side-effect imports must be in standalone
 * groups, not mixed with regular imports. This prevents unintended reordering
 * that could break code execution order.
 *
 * @param options - Options for validating side-effect groups.
 * @param options.groups - Import group configuration.
 * @param options.sortSideEffects - Whether side-effect imports can be sorted.
 * @throws {Error} If side-effect groups are incorrectly nested with regular
 *   groups.
 */
function validateSideEffectsConfig({ sortSideEffects, groups }) {
  if (sortSideEffects) {
    return
  }
  if (
    groups
      .map(group => computeGroupsNames([group]))
      .some(
        nestedGroup =>
          hasSideEffectGroup(nestedGroup) &&
          !isSideEffectOnlyGroup(nestedGroup),
      )
  ) {
    throw new Error(
      "Side effect groups cannot be nested with non side effect groups when 'sortSideEffects' is 'false'.",
    )
  }
}
function hasSideEffectGroup(stringGroups) {
  return stringGroups.some(isStringGroupSideEffectOnlyGroup)
}
export { validateSideEffectsConfig }
