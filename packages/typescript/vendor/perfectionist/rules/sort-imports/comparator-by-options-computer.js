import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { computeOrderedValue } from '../../utils/compare/compute-ordered-value.js'
import {
  buildStringComparatorByOptionsComputer,
  defaultComparatorByOptionsComputer,
} from '../../utils/compare/default-comparator-by-options-computer.js'
let comparatorByOptionsComputer = options => {
  switch (options.type) {
    case 'type-import-first':
      return (a, b) => compareTypeImportFirst(a, b, options)
    case 'subgroup-order':
    case 'alphabetical':
    case 'line-length':
    case 'unsorted':
    case 'natural':
    case 'custom':
      switch (options.sortBy) {
        case 'specifier':
          return bySpecifierComparatorByOptionsComputer({
            ...options,
            type: options.type,
          })
        case 'path':
          return defaultComparatorByOptionsComputer({
            ...options,
            type: options.type,
          })
        /* v8 ignore next 2 -- @preserve Exhaustive guard. */
        default:
          throw new UnreachableCaseError(options.sortBy)
      }
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(options.type)
  }
}
/**
 * Compares two import nodes to sort type imports before regular imports.
 *
 * When both nodes are type imports or both are regular imports, returns 0
 * (equal). Otherwise, sorts type imports first based on the order option.
 *
 * @param a - The first import sorting node.
 * @param b - The second import sorting node.
 * @param options - Options containing the sort order.
 * @returns A negative number if a should come first, positive if b should.
 */
function compareTypeImportFirst(a, b, options) {
  if (a.isTypeImport && b.isTypeImport) {
    return 0
  }
  if (!a.isTypeImport && !b.isTypeImport) {
    return 0
  }
  return computeOrderedValue(a.isTypeImport ? -1 : 1, options.order)
}
let bySpecifierComparatorByOptionsComputer =
  buildStringComparatorByOptionsComputer(node => node.specifierName ?? '')
export { comparatorByOptionsComputer }
