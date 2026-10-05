import { isContextOptionMatching } from '../../utils/context-matching/is-context-option-matching.js'
import { computeNodeName } from './compute-node-name.js'
/**
 * Computes the matched context options for a given enum node.
 *
 * @param params - Parameters.
 * @param params.enumMembers - The enum members of the enum declaration node.
 * @param params.matchedAstSelectors - The matched AST selectors for an enum
 *   node.
 * @param params.context - The rule context.
 * @returns The matched context options or undefined if none match.
 */
function computeMatchedContextOptions({
  matchedAstSelectors,
  enumMembers,
  context,
}) {
  let nodeNames = enumMembers.map(enumMember =>
    computeNodeName({
      sourceCode: context.sourceCode,
      node: enumMember,
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
