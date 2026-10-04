import { UnreachableCaseError } from '../../../utils/unreachable-case-error.js'
import '../../../utils/assert-is-never.js'
import { AST_NODE_TYPES } from '../../../../ast-node-types/index.cjs'
function computeAccessibilityModifier({ hasPrivateHash, node }) {
  if (hasPrivateHash) {
    return ['private']
  }
  switch (node.accessibility) {
    case 'protected':
      return ['protected']
    case 'private':
      return ['private']
    case void 0:
    case 'public':
      return ['public']
    default:
      node.accessibility
      return computeUnhandledAccessibilityModifier(node.accessibility)
  }
  function computeUnhandledAccessibilityModifier(modifier) {
    /* v8 ignore else --  @preserve Unhandled case */
    if (modifier === null) {
      return ['public']
    }
    /* v8 ignore next -- @preserve Unhandled case */
    throw new Error('Unhandled accessibility modifier')
  }
}
function computeAbstractModifier(node) {
  switch (node.type) {
    case AST_NODE_TYPES.TSAbstractPropertyDefinition:
    case AST_NODE_TYPES.TSAbstractMethodDefinition:
    case AST_NODE_TYPES.TSAbstractAccessorProperty:
      return ['abstract']
    case AST_NODE_TYPES.PropertyDefinition:
    case AST_NODE_TYPES.MethodDefinition:
    case AST_NODE_TYPES.AccessorProperty:
      return []
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node)
  }
}
function computeAsyncModifier(node) {
  return node.async ? ['async'] : []
}
function computeStaticModifier(node) {
  return node.static ? ['static'] : []
}
function computeReadonlyModifier(node) {
  return node.readonly ? ['readonly'] : []
}
function computeOverrideModifier(node) {
  return node.override ? ['override'] : []
}
function computeOptionalModifier(node) {
  return node.optional ? ['optional'] : []
}
function computeDecoratedModifier(isDecorated) {
  return isDecorated ? ['decorated'] : []
}
export {
  computeAbstractModifier,
  computeAccessibilityModifier,
  computeAsyncModifier,
  computeDecoratedModifier,
  computeOptionalModifier,
  computeOverrideModifier,
  computeReadonlyModifier,
  computeStaticModifier,
}
