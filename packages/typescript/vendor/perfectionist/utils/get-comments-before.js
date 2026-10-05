/**
 * Returns a list of comments before a given node, excluding ones that are right
 * after code. Includes comment blocks, ignore shebang comments.
 *
 * @param params - Parameters object.
 * @param params.node - The node to get comments before.
 * @param params.sourceCode - The source code object.
 * @param [params.tokenValueToIgnoreBefore] - Allows the following token to
 *   directly precede the node.
 * @returns An array of comments before the given node.
 */
function getCommentsBefore({ tokenValueToIgnoreBefore, sourceCode, node }) {
  let commentsBefore = getRelevantCommentsBeforeNodeOrToken(sourceCode, node)
  let tokenBeforeNode = sourceCode.getTokenBefore(node)
  if (
    !tokenValueToIgnoreBefore ||
    commentsBefore.length > 0 ||
    tokenBeforeNode?.value !== tokenValueToIgnoreBefore
  ) {
    return commentsBefore
  }
  return getRelevantCommentsBeforeNodeOrToken(sourceCode, tokenBeforeNode)
}
function getRelevantCommentsBeforeNodeOrToken(source, node) {
  return source
    .getCommentsBefore(node)
    .filter(comment => !isShebangComment(comment))
    .filter(comment => {
      return (
        source.getTokenBefore(comment)?.loc.end.line !== comment.loc.start.line
      )
    })
}
function isShebangComment(comment) {
  return comment.type === 'Shebang' || comment.type === 'Hashbang'
}
export { getCommentsBefore }
