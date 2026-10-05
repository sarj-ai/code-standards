import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the dependency names of an import-like AST node.
 *
 * @param props - The parameters object.
 * @param props.sourceCode - ESLint source code object for text extraction.
 * @param props.node - The AST node representing an import-like declaration.
 * @returns The names of the dependencies.
 */
function computeDependencyNames({ sourceCode, node }) {
  switch (node.type) {
    case AST_NODE_TYPES.TSImportEqualsDeclaration:
      return [node.id.name]
    case AST_NODE_TYPES.VariableDeclaration:
      return []
    case AST_NODE_TYPES.ImportDeclaration:
      return node.specifiers.map(computeImportClauseDependencyName)
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(node)
  }
  function computeImportClauseDependencyName(specifier) {
    switch (specifier.type) {
      case AST_NODE_TYPES.ImportNamespaceSpecifier:
      case AST_NODE_TYPES.ImportDefaultSpecifier:
        return sourceCode.getText(specifier.local)
      case AST_NODE_TYPES.ImportSpecifier:
        return sourceCode.getText(specifier.imported)
      /* v8 ignore next 2 -- @preserve Exhaustive guard. */
      default:
        throw new UnreachableCaseError(specifier)
    }
  }
}
export { computeDependencyNames }
