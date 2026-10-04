import { buildCustomGroupSelectorJsonSchema } from '../../utils/json-schemas/common-groups-json-schemas.js'
/**
 * Complete list of available selectors for array elements. Used for validation
 * and JSON schema generation.
 */
let allSelectors = ['literal']
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
}
export { additionalCustomGroupMatchOptionsJsonSchema, allSelectors }
