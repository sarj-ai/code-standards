import { UnreachableCaseError } from '../unreachable-case-error.js'
import { buildSubgroupOrderComparator } from './build-subgroup-order-comparator.js'
import { buildLineLengthComparator } from './build-line-length-comparator.js'
import { compareAlphabetically } from './compare-alphabetically.js'
import { compareByCustomSort } from './compare-by-custom-sort.js'
import { unsortedComparator } from './unsorted-comparator.js'
import { compareNaturally } from './compare-naturally.js'
/**
 * Builds a comparator computer that compares sorting nodes by a string computed
 * from each node, according to the sort type of the options.
 *
 * Sort types that do not compare strings, such as line length or subgroup
 * order, ignore the computed string.
 *
 * @param computeValue - Computes the string to compare for a sorting node.
 * @returns A function that computes a comparator from sorting options.
 */
function buildStringComparatorByOptionsComputer(computeValue) {
  return options => {
    switch (options.type) {
      case 'subgroup-order':
        if (!options.groups) {
          return unsortedComparator
        }
        return buildSubgroupOrderComparator({
          ...options,
          groups: options.groups,
        })
      case 'alphabetical':
        return (a, b) =>
          compareAlphabetically(computeValue(a), computeValue(b), options)
      case 'line-length':
        return buildLineLengthComparator(options)
      case 'unsorted':
        return unsortedComparator
      case 'natural':
        return (a, b) =>
          compareNaturally(computeValue(a), computeValue(b), options)
      case 'custom':
        return (a, b) =>
          compareByCustomSort(computeValue(a), computeValue(b), options)
      /* v8 ignore next 2 -- @preserve Exhaustive guard. */
      default:
        throw new UnreachableCaseError(options.type)
    }
  }
}
let defaultComparatorByOptionsComputer = buildStringComparatorByOptionsComputer(
  node => node.name,
)
export {
  buildStringComparatorByOptionsComputer,
  defaultComparatorByOptionsComputer,
}
