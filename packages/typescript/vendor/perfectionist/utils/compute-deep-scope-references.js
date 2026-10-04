/**
 * Recursively computes all scope references deeply for a given node.
 *
 * @param node - The AST node.
 * @param sourceCode - The source code object.
 * @returns The list of scope references.
 */
function computeDeepScopeReferences(node, sourceCode) {
  return computeScopeReference(sourceCode.getScope(node))
  function computeScopeReference(scope) {
    return [
      ...scope.references,
      ...scope.childScopes.flatMap(computeScopeReference),
    ]
  }
}
export { computeDeepScopeReferences }
