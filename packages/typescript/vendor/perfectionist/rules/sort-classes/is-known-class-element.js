import '../../utils/assert-is-never.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Checks whether a class element is supported by the sort-classes rule.
 *
 * Unknown elements should be ignored to avoid crashes with non-standard parsers
 * while letting known elements keep their ordering behavior.
 *
 * @param member - The class element to check.
 * @returns True when the element is a known, supported class member.
 */
function isKnownClassElement(member) {
  switch (member.type) {
    case AST_NODE_TYPES.TSAbstractPropertyDefinition:
    case AST_NODE_TYPES.TSAbstractMethodDefinition:
    case AST_NODE_TYPES.TSAbstractAccessorProperty:
    case AST_NODE_TYPES.PropertyDefinition:
    case AST_NODE_TYPES.MethodDefinition:
    case AST_NODE_TYPES.AccessorProperty:
    case AST_NODE_TYPES.TSIndexSignature:
    case AST_NODE_TYPES.StaticBlock:
      return true
    default:
      return false
  }
}
export { isKnownClassElement }
