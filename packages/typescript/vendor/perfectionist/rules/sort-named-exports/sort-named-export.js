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
import { computeExportKindModifier } from './compute-export-kind-modifier.js'
/**
 * Cache computed groups by modifiers and selectors for performance.
 */
let cachedGroupsByModifiersAndSelectors = /* @__PURE__ */ new Map()
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  newlinesInside: 'newlinesBetween',
  specialCharacters: 'keep',
  partitionByNewLine: false,
  partitionByComment: false,
  newlinesBetween: 'ignore',
  useConfigurationIf: {},
  type: 'alphabetical',
  ignoreAlias: false,
  customGroups: [],
  ignoreCase: true,
  locales: 'en-US',
  alphabet: '',
  order: 'asc',
  groups: [],
}
function sortNamedExport({ matchedAstSelectors, context, node }) {
  if (!isSortable(node.specifiers)) {
    return
  }
  let settings = getSettings(context.settings)
  let matchedContextOptions = computeMatchedContextOptions({
    matchedAstSelectors,
    context,
    node,
  })
  let options = complete(matchedContextOptions, settings, defaultOptions)
  validateCustomSortConfig(options)
  validateGroupsConfig({
    modifiers: allModifiers,
    selectors: allSelectors,
    options,
  })
  validateNewlinesAndPartitionConfig(options)
  let { sourceCode, id } = context
  let eslintDisabledLines = getEslintDisabledLines({
    ruleName: id,
    sourceCode,
  })
  let optionsByGroupIndexComputer = buildOptionsByGroupIndexComputer(options)
  let formattedMembers = [[]]
  for (let specifier of node.specifiers) {
    let name = computeNodeName(specifier, options.ignoreAlias)
    let selector = 'export'
    let modifiers = [computeExportKindModifier(specifier)]
    let predefinedGroups = generatePredefinedGroups({
      cache: cachedGroupsByModifiersAndSelectors,
      selectors: [selector],
      modifiers,
    })
    let group = computeGroup({
      customGroupMatcher: customGroup =>
        doesCustomGroupMatch({
          selectors: [selector],
          elementName: name,
          customGroup,
          modifiers,
        }),
      predefinedGroups,
      options,
    })
    let sortingNode = {
      isEslintDisabled: isNodeEslintDisabled(specifier, eslintDisabledLines),
      size: rangeToDiff(specifier, sourceCode),
      node: specifier,
      group,
      name,
    }
    let lastSortingNode = formattedMembers.at(-1)?.at(-1)
    if (
      shouldPartition({
        lastSortingNode,
        sortingNode,
        sourceCode,
        options,
      })
    ) {
      formattedMembers.push([])
    }
    formattedMembers.at(-1).push({
      ...sortingNode,
      partitionId: formattedMembers.length,
    })
  }
  function sortNodesExcludingEslintDisabled(ignoreEslintDisabledNodes) {
    return formattedMembers.flatMap(groupedNodes =>
      sortNodesByGroups({
        comparatorByOptionsComputer: defaultComparatorByOptionsComputer,
        optionsByGroupIndexComputer,
        ignoreEslintDisabledNodes,
        groups: options.groups,
        nodes: groupedNodes,
      }),
    )
  }
  let nodes = formattedMembers.flat()
  reportAllErrors({
    availableMessageIds: {
      missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
      extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
      unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
      unexpectedOrder: ORDER_ERROR_ID,
    },
    sortNodesExcludingEslintDisabled,
    options,
    context,
    nodes,
  })
}
export { defaultOptions, sortNamedExport }
