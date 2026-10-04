import { isContextOptionMatching } from '../../utils/context-matching/is-context-option-matching.js'
import { computeNodeName } from './compute-node-name.js'
/**
 * Computes the matched context options for a given heritage clause parent node.
 *
 * @param params - Parameters.
 * @param params.heritageClauses - The heritage clauses of the parent node.
 * @param params.matchedAstSelectors - The matched AST selectors for an object
 *   node.
 * @param params.context - The rule context.
 * @returns The matched context options or undefined if none match.
 */
function computeMatchedContextOptions({
  matchedAstSelectors,
  heritageClauses,
  context,
}) {
  let nodeNames = heritageClauses.map(clause =>
    computeNodeName(clause.expression),
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
