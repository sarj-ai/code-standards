import {
  buildFallbackSortJsonSchema,
  buildRegexJsonSchema,
  buildTypeJsonSchema,
  orderJsonSchema,
} from './common-json-schemas.js'
/**
 * JSON schema for the newlines between option. Validates configuration for
 * adding newlines between different groups.
 */
let newlinesBetweenJsonSchema = {
  oneOf: [
    {
      description: 'Specifies how to handle newlines between groups.',
      enum: ['ignore'],
      type: 'string',
    },
    {
      type: 'number',
      minimum: 0,
    },
  ],
}
/**
 * JSON schema for the newlines inside option.
 */
let newlinesInsideJsonSchema = {
  oneOf: [
    {
      description: 'Specifies how to handle newlines between groups elements',
      enum: ['ignore'],
      type: 'string',
    },
    {
      type: 'number',
      minimum: 0,
    },
  ],
}
function buildGroupsJsonSchema({
  allowedAdditionalTypeValues,
  additionalSortProperties,
}) {
  return {
    items: {
      oneOf: [
        { type: 'string' },
        {
          items: { type: 'string' },
          type: 'array',
          minItems: 1,
        },
        {
          properties: { newlinesBetween: newlinesBetweenJsonSchema },
          required: ['newlinesBetween'],
          additionalProperties: false,
          type: 'object',
        },
        {
          properties: {
            group: {
              oneOf: [
                { type: 'string' },
                {
                  items: { type: 'string' },
                  type: 'array',
                  minItems: 1,
                },
              ],
            },
            fallbackSort: buildFallbackSortJsonSchema({
              additionalProperties: additionalSortProperties,
              allowedAdditionalTypeValues,
            }),
            commentAbove: {
              description: 'Specifies a comment to enforce above the group.',
              type: 'string',
            },
            type: buildTypeJsonSchema({
              allowedAdditionalValues: allowedAdditionalTypeValues,
            }),
            newlinesInside: newlinesInsideJsonSchema,
            order: orderJsonSchema,
            ...additionalSortProperties,
          },
          additionalProperties: false,
          required: ['group'],
          minProperties: 2,
          type: 'object',
        },
      ],
    },
    description: 'Specifies a list of groups for sorting.',
    type: 'array',
  }
}
/**
 * Builds JSON schema for custom groups array configuration.
 *
 * Creates a schema that validates an array of custom group definitions.
 * Supports both single custom groups and "anyOf" groups containing multiple
 * subgroups. Each group must have a groupName and can include various matching
 * criteria.
 *
 * @example
 *
 * ```ts
 * // Valid configuration:
 * ;[
 *   {
 *     groupName: 'react',
 *     anyOf: [{ elementNamePattern: 'use*' }, { selector: 'hook' }],
 *   },
 *   {
 *     groupName: 'utils',
 *     elementNamePattern: '*Utils',
 *   },
 * ]
 * ```
 *
 * @param options - Configuration options.
 * @param options.additionalSortProperties - Extra properties for sorting.
 * @param options.additionalCustomGroupMatchProperties - Extra properties for
 *   matching custom groups.
 * @returns JSON schema for custom groups array validation.
 */
function buildCustomGroupsArrayJsonSchema({
  additionalCustomGroupMatchProperties,
  allowedAdditionalTypeValues,
  additionalSortProperties,
}) {
  let commonCustomGroupJsonSchemas = buildCommonCustomGroupJsonSchemas({
    allowedAdditionalTypeValues,
    additionalSortProperties,
  })
  let populatedCustomGroupMatchOptionsJsonSchema =
    buildPopulatedCustomGroupMatchPropertiesJsonSchema(
      additionalCustomGroupMatchProperties,
    )
  return {
    items: {
      oneOf: [
        {
          properties: {
            ...commonCustomGroupJsonSchemas,
            anyOf: {
              items: {
                properties: populatedCustomGroupMatchOptionsJsonSchema,
                description: 'Custom group.',
                additionalProperties: false,
                type: 'object',
              },
              type: 'array',
              minItems: 1,
            },
          },
          description: 'Custom group block.',
          required: ['groupName', 'anyOf'],
          additionalProperties: false,
          type: 'object',
        },
        {
          properties: {
            ...commonCustomGroupJsonSchemas,
            ...populatedCustomGroupMatchOptionsJsonSchema,
          },
          description: 'Custom group.',
          additionalProperties: false,
          required: ['groupName'],
          minProperties: 2,
          type: 'object',
        },
      ],
    },
    description: 'Defines custom groups to match specific members.',
    type: 'array',
  }
}
function buildCommonGroupsJsonSchemas({
  additionalCustomGroupMatchProperties,
  allowedAdditionalTypeValues,
  additionalSortProperties,
} = {}) {
  return {
    customGroups: buildCustomGroupsArrayJsonSchema({
      additionalCustomGroupMatchProperties,
      allowedAdditionalTypeValues,
      additionalSortProperties,
    }),
    newlinesInside: {
      oneOf: [
        newlinesInsideJsonSchema,
        {
          enum: ['newlinesBetween'],
          type: 'string',
        },
      ],
    },
    groups: buildGroupsJsonSchema({
      allowedAdditionalTypeValues,
      additionalSortProperties,
    }),
    newlinesBetween: newlinesBetweenJsonSchema,
  }
}
/**
 * Builds JSON schema for custom group modifiers configuration.
 *
 * Creates a schema that validates an array of modifiers that must be present on
 * an element for it to match a custom group.
 *
 * @example
 *
 * ```ts
 * // For TypeScript class members:
 * buildCustomGroupModifiersJsonSchema([
 *   'static',
 *   'private',
 *   'readonly',
 *   'async',
 * ])
 * ```
 *
 * @param modifiers - Array of valid modifier names.
 * @returns JSON schema for modifiers array validation.
 */
function buildCustomGroupModifiersJsonSchema(modifiers) {
  return {
    items: {
      enum: [...modifiers],
      type: 'string',
    },
    description: 'Modifier filters.',
    type: 'array',
  }
}
/**
 * Builds JSON schema for custom group selector configuration.
 *
 * Creates a schema that validates a selector string used to match specific
 * types of elements in a custom group.
 *
 * @example
 *
 * ```ts
 * // For class members:
 * buildCustomGroupSelectorJsonSchema([
 *   'property',
 *   'method',
 *   'constructor',
 *   'accessor',
 * ])
 * ```
 *
 * @param selectors - Array of valid selector names.
 * @returns JSON schema for selector validation.
 */
function buildCustomGroupSelectorJsonSchema(selectors) {
  return {
    description: 'Selector filter.',
    enum: [...selectors],
    type: 'string',
  }
}
function buildCommonCustomGroupJsonSchemas({
  allowedAdditionalTypeValues,
  additionalSortProperties,
}) {
  return {
    fallbackSort: buildFallbackSortJsonSchema({
      additionalProperties: additionalSortProperties,
      allowedAdditionalTypeValues,
    }),
    type: buildTypeJsonSchema({
      allowedAdditionalValues: allowedAdditionalTypeValues,
    }),
    groupName: {
      description: 'Custom group name.',
      type: 'string',
    },
    newlinesInside: newlinesInsideJsonSchema,
    order: orderJsonSchema,
    ...additionalSortProperties,
  }
}
function buildPopulatedCustomGroupMatchPropertiesJsonSchema(
  customGroupMatchOptionsJsonSchema,
) {
  return {
    elementNamePattern: buildRegexJsonSchema(),
    ...customGroupMatchOptionsJsonSchema,
  }
}
export {
  buildCommonGroupsJsonSchemas,
  buildCustomGroupModifiersJsonSchema,
  buildCustomGroupSelectorJsonSchema,
  buildCustomGroupsArrayJsonSchema,
  buildGroupsJsonSchema,
  newlinesBetweenJsonSchema,
  newlinesInsideJsonSchema,
}
