import { buildCustomGroupSelectorJsonSchema } from '../../utils/json-schemas/common-groups-json-schemas.js'
const ORDER_ERROR_ID = 'unexpectedVariableDeclarationsOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedVariableDeclarationsGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenVariableDeclarationsMembers'
const MISSED_SPACING_ERROR_ID =
  'missedSpacingBetweenVariableDeclarationsMembers'
const DEPENDENCY_ORDER_ERROR_ID =
  'unexpectedVariableDeclarationsDependencyOrder'
/**
 * Array of all available selectors for variable declarations.
 *
 * Used for validation and configuration in the ESLint rule.
 */
let allSelectors = ['initialized', 'uninitialized']
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
}
export {
  DEPENDENCY_ORDER_ERROR_ID,
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
  allSelectors,
}
