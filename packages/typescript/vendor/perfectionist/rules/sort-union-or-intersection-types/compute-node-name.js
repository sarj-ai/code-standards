import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes the name of a union/intersection member.
 *
 * Multi-line parenthesized unions/intersections can include leading `|` or `&`
 * in raw source text, while formatter output often omits them. To keep sorting
 * stable across both forms, the leading separator prefix is normalized.
 *
 * @param params - Parameters object.
 * @param params.sourceCode - ESLint source code object for text extraction.
 * @param params.type - Type node represented by the member text.
 * @returns Normalized member text used for sorting and matching.
 */
function computeNodeName({ sourceCode, type }) {
  let name = sourceCode.getText(type)
  if (
    type.type !== AST_NODE_TYPES.TSUnionType &&
    type.type !== AST_NODE_TYPES.TSIntersectionType
  ) {
    return name
  }
  return name.replace(/^\s*[&|]\s*/u, '')
}
export { computeNodeName }
