import { buildRegexJsonSchema } from '../../utils/json-schemas/common-json-schemas.js'
const ORDER_ERROR_ID = 'unexpectedEnumsOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedEnumsGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenEnumsMembers'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenEnumsMembers'
const DEPENDENCY_ORDER_ERROR_ID = 'unexpectedEnumsDependencyOrder'
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  elementValuePattern: buildRegexJsonSchema(),
}
export {
  DEPENDENCY_ORDER_ERROR_ID,
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
}
