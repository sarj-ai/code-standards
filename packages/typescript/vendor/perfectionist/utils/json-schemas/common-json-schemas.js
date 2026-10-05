/**
 * JSON schema for the sort order option. Validates ascending or descending sort
 * direction.
 */
let orderJsonSchema = {
  description:
    'Specifies whether to sort items in ascending or descending order.',
  enum: ['asc', 'desc'],
  type: 'string',
}
/**
 * JSON schema for the custom alphabet option. Used with 'custom' sort type to
 * define character ordering.
 */
let alphabetJsonSchema = {
  description:
    "Used only when the `type` option is set to `'custom'`. Specifies the custom alphabet for sorting.",
  type: 'string',
}
/**
 * JSON schema for the locales option. Validates locale settings for
 * locale-aware string comparison.
 */
let localesJsonSchema = {
  oneOf: [
    { type: 'string' },
    {
      items: { type: 'string' },
      type: 'array',
    },
  ],
  description: 'Specifies the sorting locales.',
}
/**
 * JSON schema for the ignoreCase option. Controls case sensitivity in string
 * comparisons.
 */
let ignoreCaseJsonSchema = {
  description: 'Controls whether sorting should be case-sensitive or not.',
  type: 'boolean',
}
/**
 * JSON schema for the special characters handling option. Defines how special
 * characters are treated during sorting.
 */
let specialCharactersJsonSchema = {
  description:
    'Specifies whether to trim, remove, or keep special characters before sorting.',
  enum: ['remove', 'trim', 'keep'],
  type: 'string',
}
let matchesAstSelectorJsonSchema = {
  description:
    'Specifies an AST selector to match elements for conditional configuration.',
  type: 'string',
}
/**
 * Builds a collection of common JSON schemas used across sorting rules.
 *
 * Creates schemas for standard sorting options that are shared by multiple
 * rules. This ensures consistent validation across the plugin.
 *
 * @param options - Configuration options.
 * @param options.additionalSortProperties - Extra sort-related option schemas
 *   to add at the root level and inside fallbackSort.
 * @returns Object containing common JSON schemas for rule validation.
 */
function buildCommonJsonSchemas({
  allowedAdditionalTypeValues,
  additionalSortProperties,
} = {}) {
  return {
    fallbackSort: buildFallbackSortJsonSchema({
      additionalProperties: additionalSortProperties,
      allowedAdditionalTypeValues,
    }),
    type: buildTypeJsonSchema({
      allowedAdditionalValues: allowedAdditionalTypeValues,
    }),
    specialCharacters: specialCharactersJsonSchema,
    ignoreCase: ignoreCaseJsonSchema,
    alphabet: alphabetJsonSchema,
    locales: localesJsonSchema,
    order: orderJsonSchema,
    ...additionalSortProperties,
  }
}
/**
 * Builds JSON schema for fallback sort configuration.
 *
 * Creates a schema for the fallback sorting option that is applied when the
 * primary sort results in equality. Allows customization through additional
 * properties.
 *
 * @param options - Configuration options.
 * @param options.additionalProperties - Extra properties to include in the
 *   schema.
 * @returns JSON schema for fallback sort validation.
 */
function buildFallbackSortJsonSchema({
  allowedAdditionalTypeValues,
  additionalProperties,
}) {
  return {
    properties: {
      type: buildTypeJsonSchema({
        allowedAdditionalValues: allowedAdditionalTypeValues,
      }),
      order: orderJsonSchema,
      ...additionalProperties,
    },
    description: 'Fallback sort order.',
    additionalProperties: false,
    required: ['type'],
    type: 'object',
  }
}
/**
 * Builds JSON schema for conditional configuration blocks.
 *
 * Creates a schema for configuration that is applied only when certain
 * conditions are met. Used for context-specific sorting rules where different
 * configurations apply based on element patterns.
 *
 * @param options - Configuration options for the conditional block.
 * @param options.additionalProperties - Extra properties to include in the
 *   schema.
 * @returns JSON schema for conditional configuration validation.
 */
function buildUseConfigIfJsonSchema({ additionalProperties } = {}) {
  return {
    description:
      'Specifies filters to match a particular options configuration for a given element to sort.',
    properties: {
      allNamesMatchPattern: buildRegexJsonSchema(),
      ...additionalProperties,
    },
    additionalProperties: false,
    type: 'object',
  }
}
function buildTypeJsonSchema({ allowedAdditionalValues }) {
  return {
    enum: [
      'alphabetical',
      'natural',
      'line-length',
      'custom',
      'unsorted',
      'subgroup-order',
      ...(allowedAdditionalValues ?? []),
    ],
    description: 'Specifies the sorting method.',
    type: 'string',
  }
}
function buildRegexJsonSchema({ additionalProperties } = {}) {
  return {
    oneOf: [
      {
        items: buildSingleRegexJsonSchema({ additionalProperties }),
        type: 'array',
      },
      buildSingleRegexJsonSchema({ additionalProperties }),
    ],
    description: 'Regular expression.',
  }
}
function buildSingleRegexJsonSchema({ additionalProperties }) {
  return {
    oneOf: [
      {
        properties: {
          ...additionalProperties,
          pattern: {
            description: 'Regular expression pattern.',
            type: 'string',
          },
          flags: {
            description: 'Regular expression flags.',
            type: 'string',
          },
        },
        additionalProperties: false,
        required: ['pattern'],
        type: 'object',
      },
      { type: 'string' },
    ],
    description: 'Regular expression.',
  }
}
let useExperimentalDependencyDetectionJsonSchema = {
  description:
    'Enables experimental dependency detection for sorting rules that support it.',
  type: 'boolean',
}
export {
  buildCommonJsonSchemas,
  buildFallbackSortJsonSchema,
  buildRegexJsonSchema,
  buildTypeJsonSchema,
  buildUseConfigIfJsonSchema,
  matchesAstSelectorJsonSchema,
  orderJsonSchema,
  useExperimentalDependencyDetectionJsonSchema,
}
