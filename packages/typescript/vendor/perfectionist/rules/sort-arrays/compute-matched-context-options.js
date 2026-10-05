import { isContextOptionMatching } from '../../utils/context-matching/is-context-option-matching.js'
import { computeNodeName } from './compute-node-name.js'
/**
 * Computes the matched context options for a given array node.
 *
 * @param params - Parameters.
 * @param params.matchedAstSelectors - The matched AST selectors for an array
 *   node.
 * @param params.elements - The array elements to compute the context options
 *   for.
 * @param params.context - The rule context.
 * @returns The matched context options or undefined if none match.
 */
function computeMatchedContextOptions({
  matchedAstSelectors,
  elements,
  context,
}) {
  let nodeNames = elements
    .filter(element => element !== null)
    .map(element =>
      computeNodeName({
        sourceCode: context.sourceCode,
        node: element,
      }),
    )
  return context.options.find(options =>
    isContextOptionMatching({
      matchedAstSelectors,
      nodeNames,
      options,
    }),
  )
}
export { computeMatchedContextOptions }
