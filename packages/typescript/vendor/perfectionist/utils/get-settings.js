/**
 * Extracts and validates Perfectionist settings from ESLint configuration.
 *
 * Retrieves global Perfectionist settings that apply to all rules. Validates
 * that only allowed settings are provided and throws an error if invalid
 * options are detected. This ensures configuration errors are caught early with
 * clear error messages.
 *
 * The settings are accessed from the 'perfectionist' key in ESLint's shared
 * configuration settings.
 *
 * @example
 *
 * ```ts
 * // Valid usage:
 * const settings = getSettings(context.settings)
 * // Returns: { type: 'natural', order: 'asc', ignoreCase: true }
 * ```
 *
 * @example
 *
 * ```ts
 * // Invalid setting throws error:
 * getSettings({
 *   perfectionist: {
 *     type: 'natural',
 *     invalidOption: true, // This will throw
 *   },
 * })
 * // Throws: Error: Invalid Perfectionist setting(s): invalidOption
 * ```
 *
 * @param settings - ESLint shared configuration settings object.
 * @returns Validated Perfectionist settings or empty object if none configured.
 * @throws {Error} If invalid settings are provided.
 */
function getSettings(settings) {
  if (!settings['perfectionist']) {
    return {}
  }
  /**
   * Identifies settings keys that are not in the allowed list.
   *
   * @param object - Settings object to validate.
   * @returns Array of invalid setting names.
   */
  function getInvalidOptions(object) {
    let allowedOptions = /* @__PURE__ */ new Set([
      'partitionByComment',
      'partitionByNewLine',
      'specialCharacters',
      'newlinesBetween',
      'newlinesInside',
      'fallbackSort',
      'ignoreCase',
      'tsconfig',
      'alphabet',
      'locales',
      'order',
      'type',
    ])
    return Object.keys(object).filter(key => !allowedOptions.has(key))
  }
  let perfectionistSettings = settings['perfectionist']
  let invalidOptions = getInvalidOptions(perfectionistSettings)
  if (invalidOptions.length > 0) {
    throw new Error(
      `Invalid Perfectionist setting(s): ${invalidOptions.join(', ')}`,
    )
  }
  return settings['perfectionist']
}
export { getSettings }
