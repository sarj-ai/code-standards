import { buildRegexJsonSchema } from '../../utils/json-schemas/common-json-schemas.js'
import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
const ORDER_ERROR_ID = 'unexpectedObjectsOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedObjectsGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenObjectMembers'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenObjectMembers'
const DEPENDENCY_ORDER_ERROR_ID = 'unexpectedObjectsDependencyOrder'
let objectParentTypes = [
  AST_NODE_TYPES.VariableDeclarator,
  AST_NODE_TYPES.CallExpression,
  AST_NODE_TYPES.Property,
]
/**
 * Array of all available selectors for object members.
 *
 * Used for validation and configuration in the ESLint rule.
 */
let allSelectors = ['member', 'method', 'property']
/**
 * Array of all available modifiers for object members.
 *
 * Used for validation and configuration in the ESLint rule.
 */
let allModifiers = ['multiline']
/**
 * Additional sort options JSON schema, Used by ESLint to validate rule options.
 */
let additionalSortOptionsJsonSchema = {
  sortBy: {
    enum: [...['name', 'value']],
    type: 'string',
  },
}
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  modifiers: buildCustomGroupModifiersJsonSchema(allModifiers),
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
  elementValuePattern: buildRegexJsonSchema(),
}
export {
  DEPENDENCY_ORDER_ERROR_ID,
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
  additionalSortOptionsJsonSchema,
  allModifiers,
  allSelectors,
  objectParentTypes,
}
