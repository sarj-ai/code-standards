/**
 * Finds all parent nodes matching one of the specified AST node types.
 *
 * @param options - Options for the search.
 * @param options.allowedTypes - Array of AST node types to match.
 * @param options.consecutiveOnly - If true, stops searching after the first
 *   non-matching parent node is found.
 * @param options.node - Starting node to search from.
 * @param options.maxParent - Optional maximum exclusive parent node to stop the
 *   search at.
 * @returns List of matching parent nodes.
 */
function computeParentNodesWithTypes({
  consecutiveOnly,
  allowedTypes,
  maxParent,
  node,
}) {
  let allowedTypesSet = new Set(allowedTypes)
  let returnValue = []
  let { parent } = node
  while (parent) {
    if (parent === maxParent) {
      break
    }
    if (allowedTypesSet.has(parent.type)) {
      returnValue.push(parent)
    } else if (consecutiveOnly) {
      break
    }
    ;({ parent } = parent)
  }
  return returnValue
}
export { computeParentNodesWithTypes }
