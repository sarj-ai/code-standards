import { matches } from './matches.js'
/**
 * Checks whether an element matches the criteria of a custom group.
 *
 * Supports both single custom groups and "anyOf" groups (where matching any
 * subgroup is sufficient). For single groups, all specified criteria must
 * match. For "anyOf" groups, at least one subgroup must match.
 *
 * @example
 *
 * ```ts
 * // Single custom group
 * doesCustomGroupMatch({
 *   customGroup: {
 *     selector: 'property',
 *     modifiers: ['static'],
 *     elementNamePattern: 'on*',
 *   },
 *   elementName: 'onClick',
 *   selectors: ['property'],
 *   modifiers: ['static', 'readonly'],
 *   elementValue: null,
 *   decoratorNames: [],
 * })
 * // Returns: true
 * ```
 *
 * @example
 *
 * ```ts
 * // AnyOf custom group
 * doesCustomGroupMatch({
 *   customGroup: {
 *     anyOf: [
 *       { selector: 'method' },
 *       { selector: 'property', modifiers: ['static'] },
 *     ],
 *   },
 *   elementName: 'foo',
 *   selectors: ['method'],
 *   modifiers: [],
 *   elementValue: null,
 * })
 * // Returns: true (matches first subgroup)
 * ```
 *
 * @template CustomGroupMatchOptions - Type of custom group match options.
 * @param props - Combined parameters including the custom group and element
 *   properties.
 * @returns True if the element matches the custom group criteria, false
 *   otherwise.
 */
function doesCustomGroupMatch(props) {
  if ('anyOf' in props.customGroup) {
    return props.customGroup.anyOf.some(subgroup =>
      doesSingleCustomGroupMatch({
        ...props,
        customGroup: subgroup,
      }),
    )
  }
  return doesSingleCustomGroupMatch({
    ...props,
    customGroup: props.customGroup,
  })
}
/**
 * Checks whether an element matches a single custom group's criteria.
 *
 * Tests each criterion in sequence, returning false as soon as any criterion
 * fails. All specified criteria must match for the function to return true. The
 * checks are performed in the following order:
 *
 * 1. Selector match (exact)
 * 2. Modifiers match (all required modifiers must be present)
 * 3. Element name pattern match
 * 4. Element value pattern match
 * 5. Decorator name pattern match (at least one decorator must match).
 *
 * @param params - Parameters for matching.
 * @param params.customGroup - Custom group configuration with matching
 *   criteria.
 * @param params.elementName - Name of the element to test.
 * @param params.elementValue - Optional value of the element.
 * @param params.selectors - Element's selectors.
 * @param params.modifiers - Element's modifiers.
 * @param params.decoratorNames - Element's decorator names.
 * @returns True if all specified criteria match, false otherwise.
 */
function doesSingleCustomGroupMatch({
  decoratorNames,
  elementValue,
  customGroup,
  elementName,
  selectors,
  modifiers,
}) {
  if (customGroup.selector && !selectors?.includes(customGroup.selector)) {
    return false
  }
  if (customGroup.modifiers) {
    for (let modifier of customGroup.modifiers) {
      if (!modifiers?.includes(modifier)) {
        return false
      }
    }
  }
  if ('elementNamePattern' in customGroup && customGroup.elementNamePattern) {
    if (!matches(elementName, customGroup.elementNamePattern)) {
      return false
    }
  }
  if ('elementValuePattern' in customGroup && customGroup.elementValuePattern) {
    if (!matches(elementValue ?? '', customGroup.elementValuePattern)) {
      return false
    }
  }
  if (
    'decoratorNamePattern' in customGroup &&
    customGroup.decoratorNamePattern
  ) {
    let decoratorPattern = customGroup.decoratorNamePattern
    if (
      !decoratorNames?.some(decorator => matches(decorator, decoratorPattern))
    ) {
      return false
    }
  }
  return true
}
export { doesCustomGroupMatch }
