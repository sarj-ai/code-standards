import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Determines whether the given AST node is a non-external-reference TS import
 * equals declaration.
 *
 * @param node - The AST node representing an import-like declaration.
 * @returns True if the node is a non-external-reference TS import equals
 *   declaration; otherwise, false.
 */
function isNonExternalReferenceTsImportEquals(node) {
  if (node.type !== AST_NODE_TYPES.TSImportEqualsDeclaration) {
    return false
  }
  return node.moduleReference.type !== AST_NODE_TYPES.TSExternalModuleReference
}
export { isNonExternalReferenceTsImportEquals }
