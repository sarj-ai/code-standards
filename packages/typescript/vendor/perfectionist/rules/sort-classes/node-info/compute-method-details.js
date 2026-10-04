import { UnreachableCaseError } from '../../../utils/unreachable-case-error.js'
import {
  computeAbstractModifier,
  computeAccessibilityModifier,
  computeAsyncModifier,
  computeDecoratedModifier,
  computeOptionalModifier,
  computeOverrideModifier,
  computeStaticModifier,
} from './common-modifiers.js'
import { computeMethodOrPropertyNameDetails } from './compute-method-or-property-name-details.js'
import { AST_NODE_TYPES } from '../../../../ast-node-types/index.cjs'
/**
 * Computes details related to a method.
 *
 * @param params - Parameters object.
 * @param params.isDecorated - Whether the accessor is decorated.
 * @param params.method - The method node to compute information for.
 * @param params.sourceCode - The source code object.
 * @param params.hasParentDeclare - Whether the parent class is a declare class.
 * @returns An object containing various details about the method.
 */
function computeMethodDetails({
  hasParentDeclare,
  isDecorated,
  sourceCode,
  method,
}) {
  let nameDetails = computeMethodOrPropertyNameDetails(method, sourceCode)
  return {
    modifiers: computeModifiers({
      hasPrivateHash: nameDetails.hasPrivateHash,
      isDecorated,
      method,
    }),
    addSafetySemicolonWhenInline: shouldAddSafetySemicolonWhenInline({
      hasParentDeclare,
      method,
    }),
    selectors: computeSelectors(method),
    isStatic: method.static,
    nameDetails,
  }
}
function computeSelectors(method) {
  return [...computeSetterOrConstructorSelector(), 'method']
  function computeSetterOrConstructorSelector() {
    switch (method.kind) {
      case 'constructor':
        return ['constructor']
      case 'method':
        return []
      case 'set':
        return ['set-method']
      case 'get':
        return ['get-method']
      /* v8 ignore next 2 -- @preserve Exhaustive guard. */
      default:
        throw new UnreachableCaseError(method.kind)
    }
  }
}
function computeModifiers({ hasPrivateHash, isDecorated, method }) {
  return [
    ...computeStaticModifier(method),
    ...computeAbstractModifier(method),
    ...computeDecoratedModifier(isDecorated),
    ...computeOverrideModifier(method),
    ...computeAccessibilityModifier({
      hasPrivateHash,
      node: method,
    }),
    ...computeOptionalModifier(method),
    ...computeAsyncModifier(method.value),
  ]
}
function shouldAddSafetySemicolonWhenInline({ hasParentDeclare, method }) {
  switch (method.type) {
    case AST_NODE_TYPES.TSAbstractMethodDefinition:
      return true
    case AST_NODE_TYPES.MethodDefinition:
      return hasParentDeclare
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(method)
  }
}
export { computeMethodDetails }
