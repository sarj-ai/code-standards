import {
  buildCommonJsonSchemas,
  buildUseConfigIfJsonSchema,
  matchesAstSelectorJsonSchema,
} from '../../utils/json-schemas/common-json-schemas.js'
import { buildCommonGroupsJsonSchemas } from '../../utils/json-schemas/common-groups-json-schemas.js'
import {
  partitionByCommentJsonSchema,
  partitionByNewlineJsonSchema,
} from '../../utils/json-schemas/common-partition-json-schemas.js'
import { additionalCustomGroupMatchOptionsJsonSchema } from '../sort-union-types/types.js'
function buildJsonSchema({ ignoreCallableTypes }) {
  return {
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
        partitionByComment: partitionByCommentJsonSchema,
        partitionByNewLine: partitionByNewlineJsonSchema,
        ...(ignoreCallableTypes && {
          ignoreCallableTypes: { type: 'boolean' },
        }),
      },
      additionalProperties: false,
      type: 'object',
    },
    uniqueItems: true,
    type: 'array',
  }
}
export { buildJsonSchema }
