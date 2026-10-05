import { buildCommonJsonSchemas } from '../utils/json-schemas/common-json-schemas.js'
import { buildCommonGroupsJsonSchemas } from '../utils/json-schemas/common-groups-json-schemas.js'
import {
  EXTRA_SPACING_ERROR,
  GROUP_ORDER_ERROR,
  MISSED_COMMENT_ABOVE_ERROR,
  MISSED_SPACING_ERROR,
  ORDER_ERROR,
} from '../utils/report-errors.js'
import {
  partitionByCommentJsonSchema,
  partitionByNewlineJsonSchema,
} from '../utils/json-schemas/common-partition-json-schemas.js'
import { UnreachableCaseError } from '../utils/unreachable-case-error.js'
import { defaultComparatorByOptionsComputer } from '../utils/compare/default-comparator-by-options-computer.js'
import { validateNewlinesAndPartitionConfig } from '../utils/validate-newlines-and-partition-config.js'
import { buildOptionsByGroupIndexComputer } from '../utils/build-options-by-group-index-computer.js'
import { validateCustomSortConfig } from '../utils/validate-custom-sort-config.js'
import { generatePredefinedGroups } from '../utils/generate-predefined-groups.js'
import { getEslintDisabledLines } from '../utils/get-eslint-disabled-lines.js'
import { doesCustomGroupMatch } from '../utils/does-custom-group-match.js'
import { isNodeEslintDisabled } from '../utils/is-node-eslint-disabled.js'
import { validateGroupsConfig } from '../utils/validate-groups-config.js'
import { sortNodesByGroups } from '../utils/sort-nodes-by-groups.js'
import { reportAllErrors } from '../utils/report-all-errors.js'
import { shouldPartition } from '../utils/should-partition.js'
import { computeGroup } from '../utils/compute-group.js'
import { rangeToDiff } from '../utils/range-to-diff.js'
import { getSettings } from '../utils/get-settings.js'
import { complete } from '../utils/complete.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import { isNodeOnSingleLine } from '../utils/is-node-on-single-line.js'
import {
  additionalCustomGroupMatchOptionsJsonSchema,
  allModifiers,
  allSelectors,
} from './sort-exports/types.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
/**
 * Cache computed groups by modifiers and selectors for performance.
 */
let cachedGroupsByModifiersAndSelectors = /* @__PURE__ */ new Map()
const ORDER_ERROR_ID = 'unexpectedExportsOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedExportsGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenExports'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenExports'
const MISSED_COMMENT_ABOVE_ERROR_ID = 'missedCommentAboveExport'
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  newlinesInside: 'newlinesBetween',
  specialCharacters: 'keep',
  partitionByComment: false,
  newlinesBetween: 'ignore',
  partitionByNewLine: false,
  type: 'alphabetical',
  customGroups: [],
  ignoreCase: true,
  locales: 'en-US',
  alphabet: '',
  order: 'asc',
  groups: [],
}
var sort_exports_default = createEslintRule({
  create: context => {
    let settings = getSettings(context.settings)
    let options = complete(context.options.at(0), settings, defaultOptions)
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
    let formattedMembers = [[]]
    function registerNode(node) {
      if (!node.source) {
        return
      }
      let selector = 'export'
      let modifiers = [
        computeExportKindModifier(node),
        computeExportTypeModifier(node),
        computeLineCountModifier(node),
      ]
      let name = node.source.value
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
        isEslintDisabled: isNodeEslintDisabled(node, eslintDisabledLines),
        size: rangeToDiff(node, sourceCode),
        addSafetySemicolonWhenInline: true,
        group,
        name,
        node,
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
    return {
      'Program:exit': () => {
        sortExportNodes({
          formattedMembers,
          context,
          options,
        })
      },
      ExportNamedDeclaration: registerNode,
      ExportAllDeclaration: registerNode,
    }
  },
  meta: {
    schema: {
      items: {
        properties: {
          ...buildCommonJsonSchemas(),
          ...buildCommonGroupsJsonSchemas({
            additionalCustomGroupMatchProperties:
              additionalCustomGroupMatchOptionsJsonSchema,
          }),
          partitionByComment: partitionByCommentJsonSchema,
          partitionByNewLine: partitionByNewlineJsonSchema,
        },
        additionalProperties: false,
        type: 'object',
      },
      uniqueItems: true,
      type: 'array',
    },
    messages: {
      [MISSED_COMMENT_ABOVE_ERROR_ID]: MISSED_COMMENT_ABOVE_ERROR,
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-exports',
      description: 'Enforce sorted exports.',
      recommended: true,
    },
    type: 'suggestion',
    fixable: 'code',
  },
  defaultOptions: [defaultOptions],
  name: 'sort-exports',
})
function sortExportNodes({ formattedMembers, context, options }) {
  let optionsByGroupIndexComputer = buildOptionsByGroupIndexComputer(options)
  let nodes = formattedMembers.flat()
  reportAllErrors({
    availableMessageIds: {
      missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
      extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
      missedCommentAbove: MISSED_COMMENT_ABOVE_ERROR_ID,
      unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
      unexpectedOrder: ORDER_ERROR_ID,
    },
    sortNodesExcludingEslintDisabled,
    options,
    context,
    nodes,
  })
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
}
function computeExportKindModifier(node) {
  let exportKind = 'exportKind' in node ? node.exportKind : void 0
  switch (exportKind) {
    case void 0:
    case 'value':
      return 'value'
    case 'type':
      return 'type'
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(exportKind)
  }
}
function computeExportTypeModifier(node) {
  switch (node.type) {
    case AST_NODE_TYPES.ExportNamedDeclaration:
      return 'named'
    case AST_NODE_TYPES.ExportAllDeclaration:
      return 'wildcard'
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node)
  }
}
function computeLineCountModifier(node) {
  if (isNodeOnSingleLine(node)) {
    return 'singleline'
  }
  return 'multiline'
}
export { sort_exports_default as default }
