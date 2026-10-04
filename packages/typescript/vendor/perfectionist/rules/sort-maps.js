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
import {
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
} from './sort-maps/types.js'
import {
  defaultOptions,
  sortPotentialMap,
} from './sort-maps/sort-potential-map.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
var sort_maps_default = createEslintRule({
  meta: {
    schema: {
      items: {
        properties: {
          ...buildCommonJsonSchemas(),
          ...buildCommonGroupsJsonSchemas(),
          useConfigurationIf: buildUseConfigIfJsonSchema({
            additionalProperties: {
              matchesAstSelector: matchesAstSelectorJsonSchema,
            },
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
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-maps',
      description: 'Enforce sorted Map elements.',
      recommended: true,
    },
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.NewExpression],
      sorter: sortPotentialMap,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-maps',
})
export { sort_maps_default as default }
