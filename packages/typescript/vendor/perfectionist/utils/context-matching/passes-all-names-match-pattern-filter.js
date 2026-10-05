import { matches } from '../matches.js'
/**
 * Checks if all node names match the specified pattern.
 *
 * @param params - The parameters object.
 * @param params.allNamesMatchPattern - The pattern to match against all node
 *   names.
 * @param params.nodeNames - Array of node names to test against patterns.
 * @returns True if all node names match the specified pattern, or if no pattern
 *   is specified; otherwise, false.
 */
function passesAllNamesMatchPatternFilter({ allNamesMatchPattern, nodeNames }) {
  if (!allNamesMatchPattern) {
    return true
  }
  return nodeNames.every(nodeName => matches(nodeName, allNamesMatchPattern))
}
export { passesAllNamesMatchPatternFilter }
