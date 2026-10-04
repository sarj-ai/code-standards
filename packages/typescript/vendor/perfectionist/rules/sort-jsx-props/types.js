import { buildRegexJsonSchema } from '../../utils/json-schemas/common-json-schemas.js'
import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
const ORDER_ERROR_ID = 'unexpectedJSXPropsOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedJSXPropsGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenJSXPropsMembers'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenJSXPropsMembers'
/**
 * Complete list of available JSX prop selectors. Used for validation and JSON
 * schema generation.
 */
let allSelectors = ['prop']
/**
 * Complete list of available JSX prop modifiers. Used for validation and JSON
 * schema generation.
 */
let allModifiers = ['shorthand', 'multiline']
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
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
  allModifiers,
  allSelectors,
}
