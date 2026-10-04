import {
  EXTRA_SPACING_ERROR,
  GROUP_ORDER_ERROR,
  MISSED_SPACING_ERROR,
  ORDER_ERROR,
} from '../utils/report-errors.js'
import { buildAstListeners } from '../utils/build-ast-listeners.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import { sortUnionOrIntersectionTypes } from './sort-union-or-intersection-types/sort-union-or-intersection-types.js'
import { buildJsonSchema } from './sort-union-or-intersection-types/build-json-schema.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
/**
 * Cache computed groups by modifiers and selectors for performance.
 */
let cachedGroupsByModifiersAndSelectors = /* @__PURE__ */ new Map()
const ORDER_ERROR_ID = 'unexpectedUnionTypesOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedUnionTypesGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenUnionTypes'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenUnionTypes'
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
  locales: 'en-US',
  customGroups: [],
  alphabet: '',
  order: 'asc',
  groups: [],
}
var sort_union_types_default = createEslintRule({
  meta: {
    messages: {
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-union-types',
      description: 'Enforce sorted union types.',
      recommended: true,
    },
    schema: buildJsonSchema({ ignoreCallableTypes: false }),
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.TSUnionType],
      sorter: sortUnionType,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-union-types',
})
function sortUnionType({ matchedAstSelectors, context, node }) {
  sortUnionOrIntersectionTypes({
    availableMessageIds: {
      missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
      extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
      unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
      unexpectedOrder: ORDER_ERROR_ID,
    },
    defaultOptions: {
      ...defaultOptions,
      ignoreCallableTypes: false,
    },
    cachedGroupsByModifiersAndSelectors,
    tokenValueToIgnoreBefore: '|',
    matchedAstSelectors,
    context,
    node,
  })
}
export { sort_union_types_default as default }
