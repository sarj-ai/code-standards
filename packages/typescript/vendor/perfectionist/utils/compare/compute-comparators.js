import { unsortedComparator } from './unsorted-comparator.js'
/**
 * Computes the array of comparators to use for sorting based on options.
 *
 * Returns an array containing the main comparator and a fallback comparator. If
 * the main comparator is the unsorted comparator, returns an empty array since
 * no sorting should be performed.
 *
 * @param comparatorByOptionsComputer - Function that creates a comparator from
 *   options.
 * @param options - The sorting options including fallback sort configuration.
 * @returns An array of comparators, or empty array if sorting is disabled.
 */
function computeComparators(comparatorByOptionsComputer, options) {
  let mainComparator = comparatorByOptionsComputer(options)
  if (mainComparator === unsortedComparator) {
    return []
  }
  return [
    mainComparator,
    comparatorByOptionsComputer({
      ...options,
      ...options.fallbackSort,
    }),
  ]
}
export { computeComparators }
