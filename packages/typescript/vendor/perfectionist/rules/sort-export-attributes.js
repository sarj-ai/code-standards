import {
  EXTRA_SPACING_ERROR,
  GROUP_ORDER_ERROR,
  MISSED_SPACING_ERROR,
  ORDER_ERROR,
} from '../utils/report-errors.js'
import { buildAstListeners } from '../utils/build-ast-listeners.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import { sortImportOrExportAttributes } from './sort-import-attributes/sort-import-or-export-attributes.js'
import { jsonSchema } from './sort-import-attributes.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
const ORDER_ERROR_ID = 'unexpectedExportAttributesOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedExportAttributesGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenExportAttributes'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenExportAttributes'
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
var sort_export_attributes_default = createEslintRule({
  meta: {
    messages: {
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-export-attributes',
      description: 'Enforce sorted export attributes.',
      recommended: true,
    },
    schema: jsonSchema,
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.ExportNamedDeclaration],
      sorter: sortExportAttributes,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-export-attributes',
})
function sortExportAttributes({ matchedAstSelectors, context, node }) {
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
export { sort_export_attributes_default as default }
