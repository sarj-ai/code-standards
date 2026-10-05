import { matches } from '../../utils/matches.js'
import { passesAllNamesMatchPatternFilter } from '../../utils/context-matching/passes-all-names-match-pattern-filter.js'
import { passesAstSelectorFilter } from '../../utils/context-matching/passes-ast-selector-filter.js'
import { computeNodeName } from './compute-node-name.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the matched context options for a given JSX element node.
 *
 * @param params - Parameters.
 * @param params.matchedAstSelectors - The matched AST selectors for a JSX node.
 * @param params.sourceCode - The source code object.
 * @param params.node - The JSX element node to evaluate.
 * @param params.context - The rule context.
 * @returns The matched context options or undefined if none match.
 */
function computeMatchedContextOptions({
  matchedAstSelectors,
  sourceCode,
  context,
  node,
}) {
  let nodeNames = node.openingElement.attributes
    .filter(attribute => attribute.type !== AST_NODE_TYPES.JSXSpreadAttribute)
    .map(attribute => computeNodeName(attribute))
  return context.options.find(options =>
    isContextOptionMatching({
      matchedAstSelectors,
      sourceCode,
      nodeNames,
      options,
      node,
    }),
  )
}
function isContextOptionMatching({
  matchedAstSelectors,
  sourceCode,
  nodeNames,
  options,
  node,
}) {
  if (!options.useConfigurationIf) {
    return true
  }
  return (
    passesAllNamesMatchPatternFilter({
      allNamesMatchPattern: options.useConfigurationIf.allNamesMatchPattern,
      nodeNames,
    }) &&
    passesTagMatchesPatternFilter({
      tagMatchesPattern: options.useConfigurationIf.tagMatchesPattern,
      sourceCode,
      node,
    }) &&
    passesAstSelectorFilter({
      matchesAstSelector: options.useConfigurationIf.matchesAstSelector,
      matchedAstSelectors,
    })
  )
}
function passesTagMatchesPatternFilter({
  tagMatchesPattern,
  sourceCode,
  node,
}) {
  if (!tagMatchesPattern) {
    return true
  }
  return matches(
    sourceCode.getText(node.openingElement.name),
    tagMatchesPattern,
  )
}
export { computeMatchedContextOptions }
