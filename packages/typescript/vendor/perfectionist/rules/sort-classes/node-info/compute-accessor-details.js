import {
  computeAbstractModifier,
  computeAccessibilityModifier,
  computeDecoratedModifier,
  computeOverrideModifier,
  computeStaticModifier,
} from './common-modifiers.js'
import { computeDependencyName } from '../compute-dependency-name.js'
import { computeDependencies } from '../compute-dependencies.js'
import { computeMethodOrPropertyNameDetails } from './compute-method-or-property-name-details.js'
import { isFunctionExpression } from './is-function-expression.js'
/**
 * Computes details related to an accessor property.
 *
 * @param params - Parameters object.
 * @param params.isDecorated - Whether the accessor is decorated.
 * @param params.ignoreCallbackDependenciesPatterns - Patterns to ignore when
 *   computing dependencies.
 * @param params.useExperimentalDependencyDetection - Whether to use
 *   experimental dependency detection.
 * @param params.sourceCode - The source code object.
 * @param params.className - The name of the class containing the accessor.
 * @param params.accessor - The accessor node to compute information for.
 * @returns An object containing various details about the accessor.
 */
function computeAccessorDetails({
  ignoreCallbackDependenciesPatterns,
  useExperimentalDependencyDetection,
  isDecorated,
  sourceCode,
  className,
  accessor,
}) {
  let nameDetails = computeMethodOrPropertyNameDetails(accessor, sourceCode)
  let modifiers = computeModifiers({
    hasPrivateHash: nameDetails.hasPrivateHash,
    isDecorated,
    accessor,
  })
  return {
    dependencyNames: [
      computeDependencyName({
        nodeNameWithoutStartingHash: nameDetails.nameWithoutStartingHash,
        hasPrivateHash: nameDetails.hasPrivateHash,
        isStatic: modifiers.includes('static'),
      }),
    ],
    dependencies: computeAccessorDependencies({
      ignoreCallbackDependenciesPatterns,
      useExperimentalDependencyDetection,
      className,
      accessor,
    }),
    selectors: ['accessor-property'],
    isStatic: accessor.static,
    nameDetails,
    modifiers,
  }
}
function computeAccessorDependencies({
  ignoreCallbackDependenciesPatterns,
  useExperimentalDependencyDetection,
  className,
  accessor,
}) {
  if (isFunctionExpression(accessor.value)) {
    return []
  }
  if (!accessor.value) {
    return []
  }
  return computeDependencies({
    ignoreCallbackDependenciesPatterns,
    useExperimentalDependencyDetection,
    isMemberStatic: accessor.static,
    expression: accessor.value,
    className,
  })
}
function computeModifiers({ hasPrivateHash, isDecorated, accessor }) {
  return [
    ...computeStaticModifier(accessor),
    ...computeAbstractModifier(accessor),
    ...computeDecoratedModifier(isDecorated),
    ...computeOverrideModifier(accessor),
    ...computeAccessibilityModifier({
      hasPrivateHash,
      node: accessor,
    }),
  ]
}
export { computeAccessorDetails }
