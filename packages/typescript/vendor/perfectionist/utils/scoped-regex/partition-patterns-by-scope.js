/**
 * Partitions patterns by their scope (shallow or deep).
 *
 * @param patternOrPatterns - A single pattern or an array of patterns.
 * @returns An object containing arrays of shallow and deep scope patterns.
 */
function partitionPatternsByScope(patternOrPatterns) {
  if (!Array.isArray(patternOrPatterns)) {
    let isDeepScopePattern = isDeepScopedPattern(patternOrPatterns)
    return {
      shallowScopePatterns: isDeepScopePattern ? [] : [patternOrPatterns],
      deepScopePatterns: isDeepScopePattern ? [patternOrPatterns] : [],
    }
  }
  let deepScopedPatterns = []
  let shallowScopedPatterns = []
  for (let pattern of patternOrPatterns) {
    if (isDeepScopedPattern(pattern)) {
      deepScopedPatterns.push(pattern)
    } else {
      shallowScopedPatterns.push(pattern)
    }
  }
  return {
    shallowScopePatterns: shallowScopedPatterns,
    deepScopePatterns: deepScopedPatterns,
  }
}
function isDeepScopedPattern(pattern) {
  if (typeof pattern !== 'object') {
    return false
  }
  if (!('scope' in pattern)) {
    return false
  }
  return pattern.scope === 'deep'
}
export { partitionPatternsByScope }
