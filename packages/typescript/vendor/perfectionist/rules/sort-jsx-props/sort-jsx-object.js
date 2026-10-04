import { defaultComparatorByOptionsComputer } from '../../utils/compare/default-comparator-by-options-computer.js'
import { validateNewlinesAndPartitionConfig } from '../../utils/validate-newlines-and-partition-config.js'
import { buildOptionsByGroupIndexComputer } from '../../utils/build-options-by-group-index-computer.js'
import { validateCustomSortConfig } from '../../utils/validate-custom-sort-config.js'
import { generatePredefinedGroups } from '../../utils/generate-predefined-groups.js'
import { getEslintDisabledLines } from '../../utils/get-eslint-disabled-lines.js'
import { doesCustomGroupMatch } from '../../utils/does-custom-group-match.js'
import { isNodeEslintDisabled } from '../../utils/is-node-eslint-disabled.js'
import { validateGroupsConfig } from '../../utils/validate-groups-config.js'
import { sortNodesByGroups } from '../../utils/sort-nodes-by-groups.js'
import { reportAllErrors } from '../../utils/report-all-errors.js'
import { shouldPartition } from '../../utils/should-partition.js'
import { computeGroup } from '../../utils/compute-group.js'
import { rangeToDiff } from '../../utils/range-to-diff.js'
import { getSettings } from '../../utils/get-settings.js'
import { isSortable } from '../../utils/is-sortable.js'
import { complete } from '../../utils/complete.js'
import { isNodeOnSingleLine } from '../../utils/is-node-on-single-line.js'
import {
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  allModifiers,
  allSelectors,
} from './types.js'
import { computeNodeName } from './compute-node-name.js'
import { computeMatchedContextOptions } from './compute-matched-context-options.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Cache computed groups by modifiers and selectors for performance.
 */
let cachedGroupsByModifiersAndSelectors = /* @__PURE__ */ new Map()
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  newlinesInside: 'newlinesBetween',
  specialCharacters: 'keep',
  newlinesBetween: 'ignore',
  partitionByNewLine: false,
  useConfigurationIf: {},
  type: 'alphabetical',
  ignoreCase: true,
  customGroups: [],
  locales: 'en-US',
  alphabet: '',
  order: 'asc',
  groups: [],
}
function sortJsxObject({ matchedAstSelectors, context, node }) {
  if (!isSortable(node.openingElement.attributes)) {
    return
  }
  let { sourceCode, id } = context
  let settings = getSettings(context.settings)
  let matchedContextOptions = computeMatchedContextOptions({
    matchedAstSelectors,
    sourceCode,
    context,
    node,
  })
  let options = complete(matchedContextOptions, settings, defaultOptions)
  validateCustomSortConfig(options)
  validateGroupsConfig({
    selectors: allSelectors,
    modifiers: allModifiers,
    options,
  })
  validateNewlinesAndPartitionConfig(options)
  let eslintDisabledLines = getEslintDisabledLines({
    ruleName: id,
    sourceCode,
  })
  let optionsByGroupIndexComputer = buildOptionsByGroupIndexComputer(options)
  let formattedMembers = node.openingElement.attributes.reduce(
    (accumulator, attribute) => {
      if (attribute.type === AST_NODE_TYPES.JSXSpreadAttribute) {
        accumulator.push([])
        return accumulator
      }
      let name = computeNodeName(attribute)
      let selectors = []
      let modifiers = []
      if (attribute.value === null) {
        modifiers.push('shorthand')
      }
      if (!isNodeOnSingleLine(attribute)) {
        modifiers.push('multiline')
      }
      selectors.push('prop')
      let predefinedGroups = generatePredefinedGroups({
        cache: cachedGroupsByModifiersAndSelectors,
        selectors,
        modifiers,
      })
      let group = computeGroup({
        customGroupMatcher: customGroup =>
          doesCustomGroupMatch({
            elementValue:
              attribute.value ? sourceCode.getText(attribute.value) : null,
            elementName: name,
            customGroup,
            selectors,
            modifiers,
          }),
        predefinedGroups,
        options,
      })
      let sortingNode = {
        isEslintDisabled: isNodeEslintDisabled(attribute, eslintDisabledLines),
        size: rangeToDiff(attribute, sourceCode),
        node: attribute,
        group,
        name,
      }
      let lastSortingNode = accumulator.at(-1)?.at(-1)
      if (
        shouldPartition({
          options: {
            partitionByNewLine: options.partitionByNewLine,
            partitionByComment: false,
          },
          lastSortingNode,
          sortingNode,
          sourceCode,
        })
      ) {
        accumulator.push([])
      }
      accumulator.at(-1).push({
        ...sortingNode,
        partitionId: accumulator.length,
      })
      return accumulator
    },
    [[]],
  )
  for (let currentNodes of formattedMembers) {
    function createSortNodesExcludingEslintDisabled(nodes) {
      return function (ignoreEslintDisabledNodes) {
        return sortNodesByGroups({
          comparatorByOptionsComputer: defaultComparatorByOptionsComputer,
          optionsByGroupIndexComputer,
          ignoreEslintDisabledNodes,
          groups: options.groups,
          nodes,
        })
      }
    }
    reportAllErrors({
      availableMessageIds: {
        missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
        extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
        unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
        unexpectedOrder: ORDER_ERROR_ID,
      },
      sortNodesExcludingEslintDisabled:
        createSortNodesExcludingEslintDisabled(currentNodes),
      options: {
        ...options,
        partitionByComment: false,
      },
      nodes: currentNodes,
      context,
    })
  }
}
export { defaultOptions, sortJsxObject }
