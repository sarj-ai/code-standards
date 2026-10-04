import {
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
} from '../../utils/json-schemas/common-groups-json-schemas.js'
/**
 * Complete list of available active import selectors. Used for validation and
 * JSON schema generation.
 */
let allSelectors = [
  'side-effect-style',
  'tsconfig-path',
  'side-effect',
  'external',
  'internal',
  'builtin',
  'sibling',
  'subpath',
  'import',
  'parent',
  'index',
  'style',
  'type',
]
/**
 * Complete list of available import modifiers. Used for validation and JSON
 * schema generation.
 */
let allModifiers = [
  'default',
  'multiline',
  'named',
  'require',
  'side-effect',
  'singleline',
  'ts-equals',
  'type',
  'value',
  'wildcard',
]
/**
 * Ideally, we should generate as many schemas as there are selectors, and
 * ensure that users do not enter invalid modifiers for a given selector.
 */
let additionalCustomGroupMatchOptionsJsonSchema = {
  modifiers: buildCustomGroupModifiersJsonSchema(allModifiers),
  selector: buildCustomGroupSelectorJsonSchema(allSelectors),
}
let additionalSortOptionsJsonSchema = {
  sortBy: {
    enum: [...['specifier', 'path']],
    type: 'string',
  },
}
const TYPE_IMPORT_FIRST_TYPE_OPTION = 'type-import-first'
export {
  TYPE_IMPORT_FIRST_TYPE_OPTION,
  additionalCustomGroupMatchOptionsJsonSchema,
  additionalSortOptionsJsonSchema,
  allModifiers,
  allSelectors,
}
