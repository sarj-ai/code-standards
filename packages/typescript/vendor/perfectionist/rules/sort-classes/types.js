import { buildRegexJsonSchema } from '../../utils/json-schemas/common-json-schemas.js'
import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
const ORDER_ERROR_ID = 'unexpectedClassesOrder'
const GROUP_ORDER_ERROR_ID = 'unexpectedClassesGroupOrder'
const EXTRA_SPACING_ERROR_ID = 'extraSpacingBetweenClassMembers'
const MISSED_SPACING_ERROR_ID = 'missedSpacingBetweenClassMembers'
const DEPENDENCY_ORDER_ERROR_ID = 'unexpectedClassesDependencyOrder'
/**
 * Complete list of available class member selectors. Used for validation and
 * JSON schema generation.
 */
let allSelectors = [
  'accessor-property',
  'index-signature',
  'constructor',
  'static-block',
  'get-method',
  'set-method',
  'function-property',
  'property',
  'method',
]
/**
 * Complete list of available class member modifiers. Used for validation and
 * JSON schema generation.
 */
let allModifiers = [
  'async',
  'protected',
  'private',
  'public',
  'static',
  'abstract',
  'override',
  'readonly',
  'decorated',
  'declare',
  'optional',
]
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 *
 * Note: Ideally, we should generate as many schemas as there are selectors, and
 * ensure that users do not enter invalid modifiers for a given selector.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  modifiers: buildCustomGroupModifiersJsonSchema(allModifiers),
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
  decoratorNamePattern: buildRegexJsonSchema(),
  elementValuePattern: buildRegexJsonSchema(),
}
export {
  DEPENDENCY_ORDER_ERROR_ID,
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
  allModifiers,
  allSelectors,
}
