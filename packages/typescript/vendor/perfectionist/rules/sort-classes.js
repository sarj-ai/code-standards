import {
  buildCommonJsonSchemas,
  buildRegexJsonSchema,
  buildUseConfigIfJsonSchema,
  matchesAstSelectorJsonSchema,
  useExperimentalDependencyDetectionJsonSchema,
} from '../utils/json-schemas/common-json-schemas.js'
import {
  buildCommonGroupsJsonSchemas,
  newlinesBetweenJsonSchema,
} from '../utils/json-schemas/common-groups-json-schemas.js'
import {
  DEPENDENCY_ORDER_ERROR,
  EXTRA_SPACING_ERROR,
  GROUP_ORDER_ERROR,
  MISSED_SPACING_ERROR,
  ORDER_ERROR,
} from '../utils/report-errors.js'
import {
  partitionByCommentJsonSchema,
  partitionByNewlineJsonSchema,
} from '../utils/json-schemas/common-partition-json-schemas.js'
import { buildAstListeners } from '../utils/build-ast-listeners.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import {
  DEPENDENCY_ORDER_ERROR_ID,
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
} from './sort-classes/types.js'
import { defaultOptions, sortClass } from './sort-classes/sort-class.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
var sort_classes_default = createEslintRule({
  meta: {
    schema: {
      items: {
        properties: {
          ...buildCommonJsonSchemas(),
          ...buildCommonGroupsJsonSchemas({
            additionalCustomGroupMatchProperties:
              additionalCustomGroupMatchOptionsJsonSchema,
          }),
          useConfigurationIf: buildUseConfigIfJsonSchema({
            additionalProperties: {
              matchesAstSelector: matchesAstSelectorJsonSchema,
            },
          }),
          useExperimentalDependencyDetection:
            useExperimentalDependencyDetectionJsonSchema,
          newlinesBetweenOverloadSignatures: newlinesBetweenJsonSchema,
          ignoreCallbackDependenciesPatterns: buildRegexJsonSchema(),
          partitionByComment: partitionByCommentJsonSchema,
          partitionByNewLine: partitionByNewlineJsonSchema,
        },
        additionalProperties: false,
        type: 'object',
      },
      uniqueItems: true,
      type: 'array',
    },
    messages: {
      [DEPENDENCY_ORDER_ERROR_ID]: DEPENDENCY_ORDER_ERROR,
      [MISSED_SPACING_ERROR_ID]: MISSED_SPACING_ERROR,
      [EXTRA_SPACING_ERROR_ID]: EXTRA_SPACING_ERROR,
      [GROUP_ORDER_ERROR_ID]: GROUP_ORDER_ERROR,
      [ORDER_ERROR_ID]: ORDER_ERROR,
    },
    docs: {
      url: 'https://perfectionist.dev/rules/sort-classes',
      description: 'Enforce sorted classes.',
      recommended: true,
    },
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [AST_NODE_TYPES.ClassBody],
      sorter: sortClass,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-classes',
})
export { sort_classes_default as default }
