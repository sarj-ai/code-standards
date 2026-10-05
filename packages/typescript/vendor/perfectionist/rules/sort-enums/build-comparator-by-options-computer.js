import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { unsortedComparator } from '../../utils/compare/unsorted-comparator.js'
import { compareNaturally } from '../../utils/compare/compare-naturally.js'
import {
  buildStringComparatorByOptionsComputer,
  defaultComparatorByOptionsComputer,
} from '../../utils/compare/default-comparator-by-options-computer.js'
/**
 * Builds a comparator computer function for sorting enum members.
 *
 * Creates a function that returns the appropriate comparator based on the
 * sorting options and whether the enum is numeric. Handles sorting by name or
 * by value depending on the `sortByValue` option.
 *
 * @param isNumericEnum - Whether the enum contains only numeric values.
 * @returns A comparator computer function that creates comparators from
 *   options.
 */
function buildComparatorByOptionsComputer(isNumericEnum) {
  return options => {
    switch (options.sortByValue) {
      case 'ifNumericEnum':
        if (isNumericEnum) {
          return byNumericValueComparatorComputer(options)
        }
        return defaultComparatorByOptionsComputer(options)
      case 'always':
        if (isNumericEnum) {
          return byNumericValueComparatorComputer(options)
        }
        return byNonNumericValueComparatorComputer(options)
      case 'never':
        return defaultComparatorByOptionsComputer(options)
      /* v8 ignore next 2 -- @preserve Exhaustive guard. */
      default:
        throw new UnreachableCaseError(options.sortByValue)
    }
  }
}
let byNonNumericValueComparatorComputer =
  buildStringComparatorByOptionsComputer(node => node.value ?? '')
let byNumericValueComparatorComputer = options => {
  switch (options.type) {
    /* v8 ignore next 2 -- @preserve Untested for now as not a relevant sort for this rule. */
    case 'subgroup-order':
      return defaultComparatorByOptionsComputer(options)
    case 'alphabetical':
    case 'line-length':
    case 'natural':
    case 'custom':
      return (a, b) =>
        compareNaturally(
          a.numericValue.toString(),
          b.numericValue.toString(),
          options,
        )
    case 'unsorted':
      return unsortedComparator
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(options.type)
  }
}
export { buildComparatorByOptionsComputer }
