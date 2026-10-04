import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name of an import-like AST node.
 *
 * @param props - The parameters object.
 * @param props.sourceCode - ESLint source code object for text extraction.
 * @param props.node - The AST node representing an import-like declaration.
 * @returns The name of the import.
 */
function computeNodeName({ sourceCode, node }) {
  switch (node.type) {
    case AST_NODE_TYPES.TSImportEqualsDeclaration:
      return computeImportEqualsDeclarationName(node)
    case AST_NODE_TYPES.VariableDeclaration: {
      let { value } = node.declarations[0].init.arguments[0]
      return value.toString()
    }
    case AST_NODE_TYPES.ImportDeclaration:
      return node.source.value
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node)
  }
  function computeImportEqualsDeclarationName(declaration) {
    switch (declaration.moduleReference.type) {
      case AST_NODE_TYPES.TSExternalModuleReference:
        return declaration.moduleReference.expression.value
      case AST_NODE_TYPES.TSQualifiedName:
      case AST_NODE_TYPES.Identifier:
        return sourceCode.getText(declaration.moduleReference)
      /* v8 ignore next 2 -- @preserve Exhaustive guard. */
      default:
        throw new UnreachableCaseError(declaration.moduleReference)
    }
  }
}
export { computeNodeName }
