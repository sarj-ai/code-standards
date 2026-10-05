/**
 * Check if a range contains another range.
 *
 * @param includingRange - The range that may include the other range.
 * @param subRange - The range to check if it is included.
 * @returns True if the includingRange contains the subRange, false otherwise.
 */
function rangeContainsRange(includingRange, subRange) {
  return includingRange[0] <= subRange[0] && includingRange[1] >= subRange[1]
}
export { rangeContainsRange }
