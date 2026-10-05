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
import { complete } from '../../utils/complete.js'
import { allSelectors } from '../sort-union-types/types.js'
import { computeNodeName } from './compute-node-name.js'
import { computeMatchedContextOptions } from './compute-matched-context-options.js'
import { typeContainsCallableType } from './type-contains-callable-type.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
function sortUnionOrIntersectionTypes({
  cachedGroupsByModifiersAndSelectors,
  tokenValueToIgnoreBefore,
  matchedAstSelectors,
  availableMessageIds,
  defaultOptions,
  context,
  node,
}) {
  let settings = getSettings(context.settings)
  let matchedContextOptions = computeMatchedContextOptions({
    members: node.types,
    matchedAstSelectors,
    context,
  })
  let options = complete(matchedContextOptions, settings, defaultOptions)
  validateCustomSortConfig(options)
  validateGroupsConfig({
    selectors: allSelectors,
    modifiers: [],
    options,
  })
  validateNewlinesAndPartitionConfig(options)
  if (
    options.ignoreCallableTypes &&
    node.types.some(typeContainsCallableType)
  ) {
    return
  }
  let { sourceCode, id } = context
  let eslintDisabledLines = getEslintDisabledLines({
    ruleName: id,
    sourceCode,
  })
  let optionsByGroupIndexComputer = buildOptionsByGroupIndexComputer(options)
  let formattedMembers = node.types.reduce(
    (accumulator, type) => {
      let selectors = []
      switch (type.type) {
        case AST_NODE_TYPES.TSTemplateLiteralType:
        case AST_NODE_TYPES.TSLiteralType:
          selectors.push('literal')
          break
        case AST_NODE_TYPES.TSIndexedAccessType:
        case AST_NODE_TYPES.TSTypeReference:
        case AST_NODE_TYPES.TSQualifiedName:
        case AST_NODE_TYPES.TSArrayType:
        case AST_NODE_TYPES.TSInferType:
          selectors.push('named')
          break
        case AST_NODE_TYPES.TSIntersectionType:
          selectors.push('intersection')
          break
        case AST_NODE_TYPES.TSUndefinedKeyword:
        case AST_NODE_TYPES.TSNullKeyword:
        case AST_NODE_TYPES.TSVoidKeyword:
          selectors.push('nullish')
          break
        case AST_NODE_TYPES.TSConditionalType:
          selectors.push('conditional')
          break
        case AST_NODE_TYPES.TSConstructorType:
        case AST_NODE_TYPES.TSFunctionType:
          selectors.push('function')
          break
        case AST_NODE_TYPES.TSBooleanKeyword:
        case AST_NODE_TYPES.TSUnknownKeyword:
        case AST_NODE_TYPES.TSBigIntKeyword:
        case AST_NODE_TYPES.TSNumberKeyword:
        case AST_NODE_TYPES.TSObjectKeyword:
        case AST_NODE_TYPES.TSStringKeyword:
        case AST_NODE_TYPES.TSSymbolKeyword:
        case AST_NODE_TYPES.TSNeverKeyword:
        case AST_NODE_TYPES.TSAnyKeyword:
        case AST_NODE_TYPES.TSThisType:
          selectors.push('keyword')
          break
        case AST_NODE_TYPES.TSTypeOperator:
        case AST_NODE_TYPES.TSTypeQuery:
          selectors.push('operator')
          break
        case AST_NODE_TYPES.TSTypeLiteral:
        case AST_NODE_TYPES.TSMappedType:
          selectors.push('object')
          break
        case AST_NODE_TYPES.TSImportType:
          selectors.push('import')
          break
        case AST_NODE_TYPES.TSTupleType:
          selectors.push('tuple')
          break
        case AST_NODE_TYPES.TSUnionType:
          selectors.push('union')
      }
      let name = computeNodeName({
        sourceCode,
        type,
      })
      let predefinedGroups = generatePredefinedGroups({
        cache: cachedGroupsByModifiersAndSelectors,
        modifiers: [],
        selectors,
      })
      let group = computeGroup({
        customGroupMatcher: customGroup =>
          doesCustomGroupMatch({
            elementName: name,
            modifiers: [],
            customGroup,
            selectors,
          }),
        predefinedGroups,
        options,
      })
      let lastGroup = accumulator.at(-1)
      let lastSortingNode = lastGroup?.at(-1)
      let sortingNode = {
        isEslintDisabled: isNodeEslintDisabled(type, eslintDisabledLines),
        size: rangeToDiff(type, sourceCode),
        node: type,
        group,
        name,
      }
      if (
        shouldPartition({
          tokenValueToIgnoreBefore,
          lastSortingNode,
          sortingNode,
          sourceCode,
          options,
        })
      ) {
        lastGroup = []
        accumulator.push(lastGroup)
      }
      lastGroup?.push({
        ...sortingNode,
        partitionId: accumulator.length,
      })
      return accumulator
    },
    [[]],
  )
  for (let nodes of formattedMembers) {
    reportAllErrors({
      sortNodesExcludingEslintDisabled:
        createSortNodesExcludingEslintDisabled(nodes),
      availableMessageIds,
      options,
      context,
      nodes,
    })
  }
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
}
export { sortUnionOrIntersectionTypes }
