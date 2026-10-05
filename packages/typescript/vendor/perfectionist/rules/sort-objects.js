import {
  buildCommonJsonSchemas,
  buildRegexJsonSchema,
  buildUseConfigIfJsonSchema,
  matchesAstSelectorJsonSchema,
  useExperimentalDependencyDetectionJsonSchema,
} from '../utils/json-schemas/common-json-schemas.js'
import { buildCommonGroupsJsonSchemas } from '../utils/json-schemas/common-groups-json-schemas.js'
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
import { scopedRegexJsonSchema } from '../utils/json-schemas/scoped-regex-json-schema.js'
import {
  DEPENDENCY_ORDER_ERROR_ID,
  EXTRA_SPACING_ERROR_ID,
  GROUP_ORDER_ERROR_ID,
  MISSED_SPACING_ERROR_ID,
  ORDER_ERROR_ID,
  additionalCustomGroupMatchOptionsJsonSchema,
  additionalSortOptionsJsonSchema,
} from './sort-objects/types.js'
import { defaultOptions, sortObject } from './sort-objects/sort-object.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
var sort_objects_default = createEslintRule({
  meta: {
    schema: {
      items: {
        properties: {
          ...buildCommonJsonSchemas({
            additionalSortProperties: additionalSortOptionsJsonSchema,
          }),
          ...buildCommonGroupsJsonSchemas({
            additionalCustomGroupMatchProperties:
              additionalCustomGroupMatchOptionsJsonSchema,
            additionalSortProperties: additionalSortOptionsJsonSchema,
          }),
          useConfigurationIf: buildUseConfigIfJsonSchema({
            additionalProperties: {
              objectType: {
                description:
                  'Specifies whether to only match destructured objects or regular objects.',
                enum: ['destructured', 'non-destructured'],
                type: 'string',
              },
              hasNumericKeysOnly: {
                description:
                  'Specifies whether to only match objects that have exclusively numeric keys.',
                type: 'boolean',
              },
              declarationCommentMatchesPattern: scopedRegexJsonSchema,
              callingFunctionNamePattern: scopedRegexJsonSchema,
              matchesAstSelector: matchesAstSelectorJsonSchema,
              declarationMatchesPattern: scopedRegexJsonSchema,
            },
          }),
          partitionByComputedKey: {
            description:
              'Controls whether to partition objects by computed keys.',
            type: 'boolean',
          },
          styledComponents: {
            description: 'Controls whether to sort styled components.',
            type: 'boolean',
          },
          useExperimentalDependencyDetection:
            useExperimentalDependencyDetectionJsonSchema,
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
      url: 'https://perfectionist.dev/rules/sort-objects',
      description: 'Enforce sorted objects.',
      recommended: true,
    },
    type: 'suggestion',
    fixable: 'code',
  },
  create: context =>
    buildAstListeners({
      nodeTypes: [
        AST_NODE_TYPES.ObjectPattern,
        AST_NODE_TYPES.ObjectExpression,
      ],
      sorter: sortObject,
      context,
    }),
  defaultOptions: [defaultOptions],
  name: 'sort-objects',
})
export { sort_objects_default as default }
