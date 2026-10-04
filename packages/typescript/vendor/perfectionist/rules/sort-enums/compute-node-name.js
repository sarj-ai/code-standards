import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name of an enum member node.
 *
 * @param params - Parameters for group-based sorting.
 * @param params.node - The enum member node.
 * @param params.sourceCode - The source code object.
 * @returns The computed name of the enum member node.
 */
function computeNodeName({ sourceCode, node }) {
  return node.id.type === AST_NODE_TYPES.Literal ?
      node.id.value
    : sourceCode.getText(node.id)
}
export { computeNodeName }
