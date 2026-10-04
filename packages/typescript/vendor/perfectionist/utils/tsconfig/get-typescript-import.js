import { createRequire } from 'node:module'
/**
 * Cached reference to the TypeScript module.
 */
let cachedImport
/**
 * Indicates whether an attempt to load the TypeScript module has already been
 * made.
 */
let hasTriedLoadingTypescript = false
let requiredTypescriptAttributes = [
  'createModuleResolutionCache',
  'isExternalModuleNameRelative',
  'parseJsonConfigFileContent',
  'readConfigFile',
  'resolveModuleName',
  'sys',
]
/**
 * Dynamically loads the typescript module if it's available and caches it.
 *
 * @returns The TypeScript module or null if it's not available.
 */
function getTypescriptImport() {
  if (cachedImport) {
    return cachedImport
  }
  if (hasTriedLoadingTypescript) {
    return null
  }
  hasTriedLoadingTypescript = true
  try {
    let tsImport = createRequire(import.meta.url)('typescript')
    if (!isSupportedTypescriptVersion(tsImport)) {
      return null
    }
    cachedImport = tsImport
    return cachedImport
  } catch (_error) {
    return null
  }
}
function isSupportedTypescriptVersion(typescriptImport) {
  return requiredTypescriptAttributes.every(attribute =>
    Object.hasOwn(typescriptImport, attribute),
  )
}
export { getTypescriptImport }
