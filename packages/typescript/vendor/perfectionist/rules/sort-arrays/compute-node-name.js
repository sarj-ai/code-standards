import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name of an array member.
 *
 * @param props - The parameters object.
 * @param props.sourceCode - ESLint source code object for text extraction.
 * @param props.node - The AST node representing an array member.
 * @returns The name of the array member.
 */
function computeNodeName({ sourceCode, node }) {
  return node.type === AST_NODE_TYPES.Literal ?
      String(node.value)
    : sourceCode.getText(node)
}
export { computeNodeName }
