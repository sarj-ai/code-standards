import { buildCustomGroupSelectorJsonSchema } from '../../utils/json-schemas/common-groups-json-schemas.js'
/**
 * Array of all available selectors for union type members.
 *
 * Used for validation and configuration in the ESLint rule.
 */
let allSelectors = [
  'intersection',
  'conditional',
  'function',
  'operator',
  'keyword',
  'literal',
  'nullish',
  'import',
  'object',
  'named',
  'tuple',
  'union',
]
/**
 * Additional custom group match options JSON schema. Used by ESLint to validate
 * rule options at configuration time.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
}
export { additionalCustomGroupMatchOptionsJsonSchema, allSelectors }
