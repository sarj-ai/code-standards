import { name, version } from './package.json.js'
import sort_variable_declarations_default from './rules/sort-variable-declarations.js'
import sort_intersection_types_default from './rules/sort-intersection-types.js'
import sort_import_attributes_default from './rules/sort-import-attributes.js'
import sort_export_attributes_default from './rules/sort-export-attributes.js'
import sort_heritage_clauses_default from './rules/sort-heritage-clauses.js'
import sort_array_includes_default from './rules/sort-array-includes.js'
import sort_named_imports_default from './rules/sort-named-imports.js'
import sort_named_exports_default from './rules/sort-named-exports.js'
import sort_object_types_default from './rules/sort-object-types.js'
import sort_switch_case_default from './rules/sort-switch-case.js'
import sort_union_types_default from './rules/sort-union-types.js'
import sort_interfaces_default from './rules/sort-interfaces.js'
import sort_decorators_default from './rules/sort-decorators.js'
import sort_jsx_props_default from './rules/sort-jsx-props.js'
import sort_classes_default from './rules/sort-classes.js'
import sort_imports_default from './rules/sort-imports.js'
import sort_exports_default from './rules/sort-exports.js'
import sort_objects_default from './rules/sort-objects.js'
import sort_modules_default from './rules/sort-modules.js'
import sort_arrays_default from './rules/sort-arrays.js'
import sort_enums_default from './rules/sort-enums.js'
import sort_maps_default from './rules/sort-maps.js'
import sort_sets_default from './rules/sort-sets.js'
let pluginName = 'perfectionist'
let recommendedRules = {
  'sort-variable-declarations': sort_variable_declarations_default,
  'sort-intersection-types': sort_intersection_types_default,
  'sort-import-attributes': sort_import_attributes_default,
  'sort-export-attributes': sort_export_attributes_default,
  'sort-heritage-clauses': sort_heritage_clauses_default,
  'sort-array-includes': sort_array_includes_default,
  'sort-named-imports': sort_named_imports_default,
  'sort-named-exports': sort_named_exports_default,
  'sort-object-types': sort_object_types_default,
  'sort-union-types': sort_union_types_default,
  'sort-switch-case': sort_switch_case_default,
  'sort-decorators': sort_decorators_default,
  'sort-interfaces': sort_interfaces_default,
  'sort-jsx-props': sort_jsx_props_default,
  'sort-modules': sort_modules_default,
  'sort-classes': sort_classes_default,
  'sort-imports': sort_imports_default,
  'sort-exports': sort_exports_default,
  'sort-objects': sort_objects_default,
  'sort-enums': sort_enums_default,
  'sort-sets': sort_sets_default,
  'sort-maps': sort_maps_default,
}
let rules = {
  ...recommendedRules,
  'sort-arrays': sort_arrays_default,
}
let plugin = {
  meta: {
    version,
    name,
  },
  rules,
}
function getRules(options) {
  return Object.fromEntries(
    Object.keys(recommendedRules).map(ruleName => [
      `${pluginName}/${ruleName}`,
      ['error', options],
    ]),
  )
}
function createConfig(options) {
  return {
    plugins: { [pluginName]: plugin },
    rules: getRules(options),
  }
}
function createLegacyConfig(options) {
  return {
    rules: getRules(options),
    plugins: [pluginName],
  }
}
let configs = {
  'recommended-alphabetical-legacy': createLegacyConfig({
    type: 'alphabetical',
    order: 'asc',
  }),
  'recommended-line-length-legacy': createLegacyConfig({
    type: 'line-length',
    order: 'desc',
  }),
  'recommended-natural-legacy': createLegacyConfig({
    type: 'natural',
    order: 'asc',
  }),
  'recommended-custom-legacy': createLegacyConfig({
    type: 'custom',
    order: 'asc',
  }),
  'recommended-alphabetical': createConfig({
    type: 'alphabetical',
    order: 'asc',
  }),
  'recommended-line-length': createConfig({
    type: 'line-length',
    order: 'desc',
  }),
  'recommended-natural': createConfig({
    type: 'natural',
    order: 'asc',
  }),
  'recommended-custom': createConfig({
    type: 'custom',
    order: 'asc',
  }),
}
var eslint_plugin_perfectionist_default = {
  ...plugin,
  configs,
}
export { configs, eslint_plugin_perfectionist_default as default, rules }
