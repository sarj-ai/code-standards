import {
  buildCommonJsonSchemas,
  buildUseConfigIfJsonSchema,
  matchesAstSelectorJsonSchema,
} from '../utils/json-schemas/common-json-schemas.js'
import { buildCommonGroupsJsonSchemas } from '../utils/json-schemas/common-groups-json-schemas.js'
import {
  EXTRA_SPACING_ERROR,
  GROUP_ORDER_ERROR,
  MISSED_SPACING_ERROR,
  ORDER_ERROR,
} from '../utils/report-errors.js'
import {
  partitionByCommentJsonSchema,
  partitionByNewlineJsonSchema,
} from '../utils/json-schemas/common-partition-json-schemas.js'
import { buildAstListeners } from '../utils/build-ast-listeners.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import { additionalCustomGroupMatchOptionsJsonSchema } from './sort-arrays/types.js'
import { sortArray } from './sort-arrays/sort-array.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
/**
 * Cache computed groups by modifiers and selectors for performance.
 */
let cachedGroupsByModifiersAndSelectors = /* @__PURE__ */ new Map()
const ORDER_ERROR_ID = 'unexpectedArraysOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedArraysGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenArraysMembers'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenArraysMembers'
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  newlinesInside: 'newlinesBetween',
  specialCharacters: 'keep',
  partitionByComment: false,
  partitionByNewLine: false,
  newlinesBetween: 'ignore',
  useConfigurationIf: {},
  type: 'alphabetical',
  groups: ['literal'],
  ignoreCase: true,
  locales: 'en-US',
  customGroups: [],
  alphabet: '',
  order: 'asc',
}
let jsonSchema = {
  items: {
    properties: {
      ...buildCommonJsonSchemas(),
      ...buildCommonGroupsJsonSchemas({
        additionalCustomGroupMatchProperties:
          additionalCustomGroupMatchOptionsJsonSchema,
      }),
      useConfigurationIf: buildUseConfigIfJsonSchema({
        additionalProperties: {
          matchesAstSelector: matchesAstSelectorJsonSchema,
        },
      }),
      partitionByComment: partitionByCommentJsonSchema,
      partitionByNewLine: partitionByNewlineJsonSchema,
    },
    required: ['useConfigurationIf'],
    additionalProperties: false,
    type: 'object',
  },
  uniqueItems: true,
  type: 'array',
  minItems: 1,
}
var sort_arrays_default = createEslintRule({
  meta: {
    messages: {
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-arrays',
      description: 'Enforce sorted arrays.',
      recommended: false,
    },
    schema: jsonSchema,
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.NewExpression, AST_NODE_TYPES.ArrayExpression],
      context,
      sorter,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-arrays',
})
function sorter({ matchedAstSelectors, context, node }) {
  sortArray({
    availableMessageIds: {
      missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
      extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
      unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
      unexpectedOrder: ORDER_ERROR_ID,
    },
    cachedGroupsByModifiersAndSelectors,
    mustHaveMatchedContextOptions: true,
    matchedAstSelectors,
    defaultOptions,
    context,
    node,
  })
}
export { sort_arrays_default as default }
