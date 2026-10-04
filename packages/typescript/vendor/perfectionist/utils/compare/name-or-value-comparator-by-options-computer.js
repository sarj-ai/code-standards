import { UnreachableCaseError } from '../unreachable-case-error.js'
import {
  buildStringComparatorByOptionsComputer,
  defaultComparatorByOptionsComputer,
} from './default-comparator-by-options-computer.js'
let byValueComparatorByOptionsComputer = buildStringComparatorByOptionsComputer(
  node => node.value,
)
/**
 * Computes a comparator that compares sorting nodes either by name or by value,
 * depending on the `sortBy` option.
 *
 * @param options - Sorting options.
 * @returns A comparator for sorting nodes.
 */
let nameOrValueComparatorByOptionsComputer = options => {
  switch (options.sortBy) {
    case 'value':
      return byValueComparatorByOptionsComputer(options)
    case 'name':
      return defaultComparatorByOptionsComputer(options)
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(options.sortBy)
  }
}
export { nameOrValueComparatorByOptionsComputer }
