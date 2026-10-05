import { passesAllNamesMatchPatternFilter } from '../../utils/context-matching/passes-all-names-match-pattern-filter.js'
import { passesAstSelectorFilter } from '../../utils/context-matching/passes-ast-selector-filter.js'
import { computeNodeName } from './compute-node-name.js'
/**
 * Computes the matched context options for a given named export node.
 *
 * @param params - Parameters.
 * @param params.node - The named export node to compute the context options
 *   for.
 * @param params.matchedAstSelectors - The matched AST selectors for a named
 *   export node.
 * @param params.context - The rule context.
 * @returns The matched context options or undefined if none match.
 */
function computeMatchedContextOptions({ matchedAstSelectors, context, node }) {
  return context.options.find(options =>
    isContextOptionMatching({
      matchedAstSelectors,
      options,
      node,
    }),
  )
}
function isContextOptionMatching({ matchedAstSelectors, options, node }) {
  if (!options.useConfigurationIf) {
    return true
  }
  let nodeNames = node.specifiers.map(specifier =>
    computeNodeName(specifier, !!options.ignoreAlias),
  )
  return (
    passesAllNamesMatchPatternFilter({
      allNamesMatchPattern: options.useConfigurationIf.allNamesMatchPattern,
      nodeNames,
    }) &&
    passesAstSelectorFilter({
      matchesAstSelector: options.useConfigurationIf.matchesAstSelector,
      matchedAstSelectors,
    })
  )
}
export { computeMatchedContextOptions }
