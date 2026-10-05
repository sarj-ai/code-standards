import { computeDependencies } from '../compute-dependencies.js'
/**
 * Computes details related to a static block.
 *
 * @param params - Parameters object.
 * @param params.staticBlock - The static block node to compute information for.
 * @param params.ignoreCallbackDependenciesPatterns - Patterns to ignore when
 *   computing dependencies.
 * @param params.useExperimentalDependencyDetection - Whether to use
 *   experimental dependency detection.
 * @param params.className - The name of the class containing the property.
 * @returns An object containing various details about the static block.
 */
function computeStaticBlockDetails({
  ignoreCallbackDependenciesPatterns,
  useExperimentalDependencyDetection,
  staticBlock,
  className,
}) {
  return {
    dependencies: computeDependencies({
      ignoreCallbackDependenciesPatterns,
      useExperimentalDependencyDetection,
      expression: staticBlock,
      isMemberStatic: true,
      className,
    }),
    selectors: ['static-block'],
    modifiers: [],
  }
}
export { computeStaticBlockDetails }
