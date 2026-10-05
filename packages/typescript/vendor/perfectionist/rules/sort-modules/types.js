import { buildRegexJsonSchema } from '../../utils/json-schemas/common-json-schemas.js'
import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
/**
 * Complete list of available module member selectors. Used for validation and
 * JSON schema generation.
 */
let allSelectors = ['enum', 'function', 'interface', 'type', 'class']
/**
 * Complete list of available module member modifiers. Used for validation and
 * JSON schema generation.
 */
let allModifiers = ['async', 'declare', 'decorated', 'default', 'export']
/**
 * Ideally, we should generate as many schemas as there are selectors, and
 * ensure that users do not enter invalid modifiers for a given selector.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  modifiers: buildCustomGroupModifiersJsonSchema(allModifiers),
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
  decoratorNamePattern: buildRegexJsonSchema(),
}
const USAGE_TYPE_OPTION = 'usage'
export {
  USAGE_TYPE_OPTION,
  additionalCustomGroupMatchOptionsJsonSchema,
  allModifiers,
  allSelectors,
}
