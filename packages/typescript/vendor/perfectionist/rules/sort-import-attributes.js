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
import { sortImportOrExportAttributes } from './sort-import-attributes/sort-import-or-export-attributes.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
const ORDER_ERROR_ID = 'unexpectedImportAttributesOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedImportAttributesGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenImportAttributes'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenImportAttributes'
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  newlinesInside: 'newlinesBetween',
  specialCharacters: 'keep',
  partitionByComment: false,
  partitionByNewLine: false,
  newlinesBetween: 'ignore',
  useConfigurationIf: {},
  type: 'alphabetical',
  ignoreCase: true,
  customGroups: [],
  locales: 'en-US',
  alphabet: '',
  order: 'asc',
  groups: [],
}
let jsonSchema = {
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
}
var sort_import_attributes_default = createEslintRule({
  meta: {
    messages: {
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-import-attributes',
      description: 'Enforce sorted import attributes.',
      recommended: true,
    },
    schema: jsonSchema,
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.ImportDeclaration],
      sorter: sortImportAttributes,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-import-attributes',
})
function sortImportAttributes({ matchedAstSelectors, context, node }) {
  sortImportOrExportAttributes({
    availableMessageIds: {
      missedSpacingBetweenMembers: MISSED_SPACING_ERROR_ID,
      extraSpacingBetweenMembers: EXTRA_SPACING_ERROR_ID,
      unexpectedGroupOrder: GROUP_ORDER_ERROR_ID,
      unexpectedOrder: ORDER_ERROR_ID,
    },
    matchedAstSelectors,
    defaultOptions,
    context,
    node,
  })
}
export { sort_import_attributes_default as default, jsonSchema }
