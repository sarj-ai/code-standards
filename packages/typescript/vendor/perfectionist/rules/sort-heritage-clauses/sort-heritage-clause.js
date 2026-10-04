import { defaultComparatorByOptionsComputer } from '../../utils/compare/default-comparator-by-options-computer.js'
import { validateNewlinesAndPartitionConfig } from '../../utils/validate-newlines-and-partition-config.js'
import { buildOptionsByGroupIndexComputer } from '../../utils/build-options-by-group-index-computer.js'
import { validateCustomSortConfig } from '../../utils/validate-custom-sort-config.js'
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
} from './types.js'
import { computeNodeName } from './compute-node-name.js'
import { computeMatchedContextOptions } from './compute-matched-context-options.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  newlinesInside: 'newlinesBetween',
  specialCharacters: 'keep',
  newlinesBetween: 'ignore',
  partitionByNewLine: false,
  partitionByComment: false,
  useConfigurationIf: {},
  type: 'alphabetical',
  ignoreCase: true,
  customGroups: [],
  locales: 'en-US',
  alphabet: '',
  order: 'asc',
  groups: [],
}
function sortHeritageClause({ matchedAstSelectors, context, node }) {
  let heritageClauses =
    node.type === AST_NODE_TYPES.TSInterfaceDeclaration ?
      node.extends
    : node.implements
  if (!isSortable(heritageClauses)) {
    return
  }
  let settings = getSettings(context.settings)
  let matchedContextOptions = computeMatchedContextOptions({
    matchedAstSelectors,
    heritageClauses,
    context,
  })
  let options = complete(matchedContextOptions, settings, defaultOptions)
  validateCustomSortConfig(options)
  validateGroupsConfig({
    modifiers: [],
    selectors: [],
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
  for (let heritageClause of heritageClauses) {
    let name = computeNodeName(heritageClause.expression)
    let group = computeGroup({
      customGroupMatcher: customGroup =>
        doesCustomGroupMatch({
          elementName: name,
          selectors: [],
          modifiers: [],
          customGroup,
        }),
      predefinedGroups: [],
      options,
    })
    let sortingNode = {
      isEslintDisabled: isNodeEslintDisabled(
        heritageClause,
        eslintDisabledLines,
      ),
      size: rangeToDiff(heritageClause, sourceCode),
      node: heritageClause,
      partitionId: 0,
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
    formattedMembers.at(-1).push(sortingNode)
  }
  for (let nodes of formattedMembers) {
    function createSortNodesExcludingEslintDisabled(sortingNodes) {
      return function (ignoreEslintDisabledNodes) {
        return sortNodesByGroups({
          comparatorByOptionsComputer: defaultComparatorByOptionsComputer,
          optionsByGroupIndexComputer,
          ignoreEslintDisabledNodes,
          groups: options.groups,
          nodes: sortingNodes,
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
        createSortNodesExcludingEslintDisabled(nodes),
      options,
      context,
      nodes,
    })
  }
}
export { defaultOptions, sortHeritageClause }
