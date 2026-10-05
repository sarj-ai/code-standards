import { computeOrderedValue } from './compute-ordered-value.js'
import { buildStringFormatter } from './build-string-formatter.js'
import { compare } from 'natural-orderby'
/**
 * Compares two strings using natural sort order.
 *
 * Natural sorting handles embedded numbers intelligently, so "item2" comes
 * before "item10". Applies string formatting based on options before performing
 * the comparison.
 *
 * @param a - The first string to compare.
 * @param b - The second string to compare.
 * @param options - Comparison options.
 * @param options.specialCharacters - How to handle special characters.
 * @param options.ignoreCase - Whether to ignore case differences.
 * @param options.locales - The locale(s) to use for comparison.
 * @param options.order - The order direction ('asc' or 'desc').
 * @returns A negative number if a < b, positive if a > b, or 0 if equal.
 */
function compareNaturally(
  a,
  b,
  { specialCharacters, ignoreCase, locales, order },
) {
  let naturalCompare = compare({ locale: locales.toString() })
  let formatString = buildStringFormatter({
    specialCharacters,
    ignoreCase,
  })
  let result = naturalCompare(formatString(a), formatString(b))
  return computeOrderedValue(result, order)
}
export { compareNaturally }
