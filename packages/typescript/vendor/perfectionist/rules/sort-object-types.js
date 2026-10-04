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
import { computeParentNodesWithTypes } from '../utils/compute-parent-nodes-with-types.js'
import { buildAstListeners } from '../utils/build-ast-listeners.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import {
  additionalCustomGroupMatchOptionsJsonSchema,
  additionalSortOptionsJsonSchema,
  objectTypeParentTypes,
} from './sort-object-types/types.js'
import { scopedRegexJsonSchema } from '../utils/json-schemas/scoped-regex-json-schema.js'
import { sortObjectTypeElements } from './sort-object-types/sort-object-type-elements.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
const ORDER_ERROR_ID = 'unexpectedObjectTypesOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedObjectTypesGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenObjectTypeMembers'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenObjectTypeMembers'
let defaultOptions = {
  fallbackSort: {
    type: 'unsorted',
    sortBy: 'name',
  },
  newlinesInside: 'newlinesBetween',
  partitionByComment: false,
  partitionByNewLine: false,
  newlinesBetween: 'ignore',
  specialCharacters: 'keep',
  useConfigurationIf: {},
  type: 'alphabetical',
  ignoreCase: true,
  customGroups: [],
  locales: 'en-US',
  sortBy: 'name',
  alphabet: '',
  order: 'asc',
  groups: [],
}
let jsonSchema = {
  items: {
    properties: {
      ...buildCommonJsonSchemas({
        additionalSortProperties: additionalSortOptionsJsonSchema,
      }),
      ...buildCommonGroupsJsonSchemas({
        additionalCustomGroupMatchProperties:
          additionalCustomGroupMatchOptionsJsonSchema,
        additionalSortProperties: additionalSortOptionsJsonSchema,
      }),
      useConfigurationIf: buildUseConfigIfJsonSchema({
        additionalProperties: {
          hasNumericKeysOnly: {
            description:
              'Specifies whether to only match types that have exclusively numeric keys.',
            type: 'boolean',
          },
          declarationCommentMatchesPattern: scopedRegexJsonSchema,
          matchesAstSelector: matchesAstSelectorJsonSchema,
          declarationMatchesPattern: scopedRegexJsonSchema,
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
}
var sort_object_types_default = createEslintRule({
  meta: {
    messages: {
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-object-types',
      description: 'Enforce sorted object types.',
      recommended: true,
    },
    schema: jsonSchema,
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.TSTypeLiteral],
      sorter: sortObjectType,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-object-types',
})
function sortObjectType({ matchedAstSelectors, context, node }) {
  sortObjectTypeElements({
    availableMessageIds: {
      missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
      extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
      unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
      unexpectedOrder: ORDER_ERROR_ID,
    },
    parentNodes: computeObjectTypeParentNodes(node),
    elements: node.members,
    matchedAstSelectors,
    context,
  })
}
function computeObjectTypeParentNodes(node) {
  return computeParentNodesWithTypes({
    allowedTypes: [...objectTypeParentTypes],
    consecutiveOnly: false,
    maxParent: null,
    node,
  })
}
export { sort_object_types_default as default, defaultOptions, jsonSchema }
