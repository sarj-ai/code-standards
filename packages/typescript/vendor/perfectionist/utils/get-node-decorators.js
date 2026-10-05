/**
 * Safely retrieves decorators from an AST node.
 *
 * Provides a safe way to access the decorators property which may not exist on
 * all nodes or in all parser versions. Returns an empty array when decorators
 * are undefined, ensuring consistent behavior across different AST structures.
 *
 * @example
 *
 * ```ts
 * // Node without decorators
 * const plainMethod = { type: 'MethodDefinition', ... };
 * getNodeDecorators(plainMethod);
 * // Returns: []
 * ```
 *
 * @param node - AST node that may contain decorators.
 * @returns Array of decorator nodes, empty array if none exist.
 */
function getNodeDecorators(node) {
  return node.decorators ?? []
}
export { getNodeDecorators }
