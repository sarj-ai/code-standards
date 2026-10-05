import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
function computeDependencyNames(pattern) {
  let currentPattern = pattern
  while (currentPattern.type === AST_NODE_TYPES.AssignmentPattern) {
    currentPattern = currentPattern.left
  }
  switch (currentPattern.type) {
    case AST_NODE_TYPES.ObjectPattern:
      return currentPattern.properties.flatMap(
        extractNamesFromObjectPatternProperty,
      )
    case AST_NODE_TYPES.ArrayPattern:
      return currentPattern.elements.flatMap(
        extractNamesFromArrayPatternElement,
      )
    case AST_NODE_TYPES.Identifier:
      return [currentPattern.name]
    /* v8 ignore next 2 */
    default:
      return []
  }
  function extractNamesFromArrayPatternElement(element) {
    if (!element) {
      return []
    }
    if (element.type === AST_NODE_TYPES.RestElement) {
      return computeDependencyNames(element.argument)
    }
    return computeDependencyNames(element)
  }
  function extractNamesFromObjectPatternProperty(property) {
    switch (property.type) {
      case AST_NODE_TYPES.RestElement:
        return computeDependencyNames(property.argument)
      case AST_NODE_TYPES.Property:
        return computeDependencyNames(property.value)
      /* v8 ignore next 2 -- @preserve Exhaustive guard. */
      default:
        throw new UnreachableCaseError(property)
    }
  }
}
export { computeDependencyNames }
