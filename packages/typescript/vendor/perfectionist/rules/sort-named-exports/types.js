import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
const ORDER_ERROR_ID = 'unexpectedNamedExportsOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedNamedExportsGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenNamedExports'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenNamedExports'
/**
 * Array of all available selectors for named exports.
 *
 * Used for validation and configuration in the ESLint rule.
 */
let allSelectors = ['export']
/**
 * Array of all available modifiers for named exports.
 *
 * Used for validation and configuration in the ESLint rule.
 */
let allModifiers = ['value', 'type']
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  modifiers: buildCustomGroupModifiersJsonSchema(allModifiers),
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
}
export {
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
  allModifiers,
  allSelectors,
}
