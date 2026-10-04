import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
/**
 * Complete list of available export selectors. Used for validation and JSON
 * schema generation.
 */
let allSelectors = ['export']
/**
 * Complete list of available export modifiers. Used for validation and JSON
 * schema generation.
 */
let allModifiers = [
  'value',
  'type',
  'named',
  'wildcard',
  'multiline',
  'singleline',
]
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  modifiers: buildCustomGroupModifiersJsonSchema(allModifiers),
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
}
export {
  additionalCustomGroupMatchOptionsJsonSchema,
  allModifiers,
  allSelectors,
}
