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
import { computeNodeName } from './compute-node-name.js'
import { computeMatchedContextOptions } from './compute-matched-context-options.js'
function sortImportOrExportAttributes({
  matchedAstSelectors,
  availableMessageIds,
  defaultOptions,
  context,
  node,
}) {
  let attributes = node.attributes
  if (!isSortable(attributes)) {
    return
  }
  let { sourceCode, id } = context
  let settings = getSettings(context.settings)
  let matchedContextOptions = computeMatchedContextOptions({
    matchedAstSelectors,
    attributes,
    context,
  })
  let options = complete(matchedContextOptions, settings, defaultOptions)
  validateCustomSortConfig(options)
  validateGroupsConfig({
    selectors: [],
    modifiers: [],
    options,
  })
  validateNewlinesAndPartitionConfig(options)
  let eslintDisabledLines = getEslintDisabledLines({
    ruleName: id,
    sourceCode,
  })
  let optionsByGroupIndexComputer = buildOptionsByGroupIndexComputer(options)
  let formattedMembers = [[]]
  for (let attribute of attributes) {
    let name = computeNodeName(attribute, sourceCode)
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
      isEslintDisabled: isNodeEslintDisabled(attribute, eslintDisabledLines),
      size: rangeToDiff(attribute, sourceCode),
      node: attribute,
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
      sortNodesExcludingEslintDisabled:
        createSortNodesExcludingEslintDisabled(nodes),
      availableMessageIds,
      options,
      context,
      nodes,
    })
  }
}
export { sortImportOrExportAttributes }
