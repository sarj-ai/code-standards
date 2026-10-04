import {
  computeAbstractModifier,
  computeAccessibilityModifier,
  computeAsyncModifier,
  computeDecoratedModifier,
  computeOptionalModifier,
  computeOverrideModifier,
  computeReadonlyModifier,
  computeStaticModifier,
} from './common-modifiers.js'
import { computeDependencyName } from '../compute-dependency-name.js'
import { computeDependencies } from '../compute-dependencies.js'
import { computeMethodOrPropertyNameDetails } from './compute-method-or-property-name-details.js'
import { isFunctionExpression } from './is-function-expression.js'
/**
 * Computes details related to a property.
 *
 * @param params - Parameters object.
 * @param params.isDecorated - Whether the accessor is decorated.
 * @param params.property - The property node to compute information for.
 * @param params.ignoreCallbackDependenciesPatterns - Patterns to ignore when
 *   computing dependencies.
 * @param params.useExperimentalDependencyDetection - Whether to use
 *   experimental dependency detection.
 * @param params.sourceCode - The source code object.
 * @param params.className - The name of the class containing the property.
 * @returns An object containing various details about the property.
 */
function computePropertyDetails({
  ignoreCallbackDependenciesPatterns,
  useExperimentalDependencyDetection,
  isDecorated,
  sourceCode,
  className,
  property,
}) {
  let nameDetails = computeMethodOrPropertyNameDetails(property, sourceCode)
  let modifiers = computeModifiers({
    hasPrivateHash: nameDetails.hasPrivateHash,
    isDecorated,
    property,
  })
  return {
    dependencyNames: [
      computeDependencyName({
        nodeNameWithoutStartingHash: nameDetails.nameWithoutStartingHash,
        hasPrivateHash: nameDetails.hasPrivateHash,
        isStatic: modifiers.includes('static'),
      }),
    ],
    dependencies: computePropertyDependencies({
      ignoreCallbackDependenciesPatterns,
      useExperimentalDependencyDetection,
      className,
      property,
    }),
    memberValue:
      !isFunctionExpression(property.value) && property.value ?
        sourceCode.getText(property.value)
      : void 0,
    selectors: computeSelectors(property),
    isStatic: property.static,
    nameDetails,
    modifiers,
  }
}
function computeModifiers({ hasPrivateHash, isDecorated, property }) {
  return [
    ...computeStaticModifier(property),
    ...computeDeclareModifier(),
    ...computeAbstractModifier(property),
    ...computeDecoratedModifier(isDecorated),
    ...computeOverrideModifier(property),
    ...computeReadonlyModifier(property),
    ...computeAccessibilityModifier({
      hasPrivateHash,
      node: property,
    }),
    ...computeOptionalModifier(property),
    ...computeAsyncModifierIfFunctionProperty(),
  ]
  function computeDeclareModifier() {
    return property.declare ? ['declare'] : []
  }
  function computeAsyncModifierIfFunctionProperty() {
    if (!isFunctionExpression(property.value)) {
      return []
    }
    return computeAsyncModifier(property.value)
  }
}
function computePropertyDependencies({
  ignoreCallbackDependenciesPatterns,
  useExperimentalDependencyDetection,
  className,
  property,
}) {
  if (isFunctionExpression(property.value)) {
    return []
  }
  if (!property.value) {
    return []
  }
  return computeDependencies({
    ignoreCallbackDependenciesPatterns,
    useExperimentalDependencyDetection,
    isMemberStatic: property.static,
    expression: property.value,
    className,
  })
}
function computeSelectors(property) {
  return [...computeFunctionPropertySelector(), 'property']
  function computeFunctionPropertySelector() {
    return isFunctionExpression(property.value) ? ['function-property'] : []
  }
}
export { computePropertyDetails }
