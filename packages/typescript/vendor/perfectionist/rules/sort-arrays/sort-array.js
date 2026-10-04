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
import { allSelectors } from './types.js'
import { computeNodeName } from './compute-node-name.js'
import { computeMatchedContextOptions } from './compute-matched-context-options.js'
import { computeArrayElements } from './compute-array-elements.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
function sortArray({
  cachedGroupsByModifiersAndSelectors,
  mustHaveMatchedContextOptions,
  availableMessageIds,
  matchedAstSelectors,
  defaultOptions,
  context,
  node,
}) {
  let elements = computeArrayElements(node)
  if (!elements) {
    return
  }
  if (!isSortable(elements)) {
    return
  }
  let { sourceCode, id } = context
  let settings = getSettings(context.settings)
  let matchedContextOptions = computeMatchedContextOptions({
    matchedAstSelectors,
    elements,
    context,
  })
  if (mustHaveMatchedContextOptions && !matchedContextOptions) {
    return
  }
  let options = complete(matchedContextOptions, settings, defaultOptions)
  validateCustomSortConfig(options)
  validateGroupsConfig({
    selectors: allSelectors,
    modifiers: [],
    options,
  })
  validateNewlinesAndPartitionConfig(options)
  let eslintDisabledLines = getEslintDisabledLines({
    ruleName: id,
    sourceCode,
  })
  let optionsByGroupIndexComputer = buildOptionsByGroupIndexComputer(options)
  let formattedMembers = elements.reduce(
    (accumulator, element) => {
      if (element === null) {
        return accumulator
      }
      if (element.type === AST_NODE_TYPES.SpreadElement) {
        accumulator.push([])
        return accumulator
      }
      let name = computeNodeName({
        node: element,
        sourceCode,
      })
      let selector = 'literal'
      let predefinedGroups = generatePredefinedGroups({
        cache: cachedGroupsByModifiersAndSelectors,
        selectors: [selector],
        modifiers: [],
      })
      let group = computeGroup({
        customGroupMatcher: customGroup =>
          doesCustomGroupMatch({
            selectors: [selector],
            elementName: name,
            modifiers: [],
            customGroup,
          }),
        predefinedGroups,
        options,
      })
      let sortingNode = {
        isEslintDisabled: isNodeEslintDisabled(element, eslintDisabledLines),
        size: rangeToDiff(element, sourceCode),
        node: element,
        group,
        name,
      }
      let lastSortingNode = accumulator.at(-1)?.at(-1)
      if (
        shouldPartition({
          lastSortingNode,
          sortingNode,
          sourceCode,
          options,
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
  function sortNodesExcludingEslintDisabled(ignoreEslintDisabledNodes) {
    return formattedMembers.flatMap(nodes =>
      sortNodesByGroups({
        comparatorByOptionsComputer: defaultComparatorByOptionsComputer,
        optionsByGroupIndexComputer,
        ignoreEslintDisabledNodes,
        groups: options.groups,
        nodes,
      }),
    )
  }
  let nodes = formattedMembers.flat()
  reportAllErrors({
    sortNodesExcludingEslintDisabled,
    availableMessageIds,
    options,
    context,
    nodes,
  })
}
export { sortArray }
