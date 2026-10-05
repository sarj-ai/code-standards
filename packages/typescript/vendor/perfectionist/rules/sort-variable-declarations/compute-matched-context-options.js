import { isContextOptionMatching } from '../../utils/context-matching/is-context-option-matching.js'
import { computeNodeName } from './compute-node-name.js'
/**
 * Computes the matched context options for a given variable declaration node.
 *
 * @param params - Parameters.
 * @param params.node - The variable declaration node to compute the context
 *   options for.
 * @param params.matchedAstSelectors - The matched AST selectors for an object
 *   node.
 * @param params.sourceCode - The ESLint source code object.
 * @param params.context - The rule context.
 * @returns The matched context options or undefined if none match.
 */
function computeMatchedContextOptions({
  matchedAstSelectors,
  sourceCode,
  context,
  node,
}) {
  let nodeNames = node.declarations.map(declaration =>
    computeNodeName({
      node: declaration,
      sourceCode,
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
