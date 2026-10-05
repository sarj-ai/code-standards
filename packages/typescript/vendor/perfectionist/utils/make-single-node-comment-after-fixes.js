/**
 * Generates fixes to move inline trailing comments with their associated nodes.
 *
 * When a node is moved during sorting, this function ensures that any inline
 * comment on the same line (trailing comment) is moved along with it. This
 * preserves the relationship between code and its inline documentation.
 *
 * The function:
 *
 * - Detects inline comments after the sorted node
 * - Skips processing if nodes would end up on the same line
 * - Removes the comment from its original position
 * - Inserts it after the node's new position.
 *
 * @example
 *
 * ```ts
 * // Original:
 * const b = 2 // second value
 * const a = 1 // first value
 *
 * // After sorting (with comment fixes):
 * const a = 1 // first value
 * const b = 2 // second value
 * ```
 *
 * @param params - Parameters for generating comment fixes.
 * @returns Array of ESLint fix operations, empty if no inline comment exists.
 */
function makeSingleNodeCommentAfterFixes({
  sortedNode,
  sourceCode,
  fixer,
  node,
}) {
  let commentAfter = getCommentAfter(sortedNode, sourceCode)
  let areNodesOnSameLine = node.loc.start.line === sortedNode.loc.end.line
  if (!commentAfter || areNodesOnSameLine) {
    return []
  }
  let fixes = []
  let range = [
    sourceCode.getTokenBefore(commentAfter).range.at(1),
    commentAfter.range.at(1),
  ]
  fixes.push(fixer.replaceTextRange(range, ''))
  let nodeToInsertAfter = computeNodeToInsertAfter({
    sourceCode,
    node,
  })
  let commentText = computeCommentTextToInsertAfter({
    nodeToInsertAfter,
    commentAfter,
    sourceCode,
    range,
  })
  fixes.push(fixer.insertTextAfter(nodeToInsertAfter, commentText))
  return fixes
}
function computeNodeToInsertAfter({ sourceCode, node }) {
  let tokenAfterNode = sourceCode.getTokenAfter(node)
  if (tokenAfterNode?.type !== 'Punctuator') {
    return node
  }
  if (!isRelevantPunctuator(tokenAfterNode)) {
    return node
  }
  if (tokenAfterNode.loc.end.line !== node.loc.end.line) {
    return node
  }
  return tokenAfterNode
  function isRelevantPunctuator(punctuatorToken) {
    switch (punctuatorToken.value) {
      case ',':
      case ':':
        return true
      default:
        return false
    }
  }
}
function computeCommentTextToInsertAfter({
  nodeToInsertAfter,
  commentAfter,
  sourceCode,
  range,
}) {
  let commentText = sourceCode.text.slice(...range)
  if (commentAfter.type !== 'Line') {
    return commentText
  }
  if (
    sourceCode.getTokenAfter(nodeToInsertAfter)?.loc.start.line !==
    nodeToInsertAfter.loc.end.line
  ) {
    return commentText
  }
  commentText += '\n'
  return commentText
}
/**
 * Retrieves an inline comment that appears after a node on the same line.
 *
 * Searches for a comment token that:
 *
 * - Appears after the given node
 * - Is on the same line as the node's end
 * - Skips over punctuation like commas, semicolons, and colons.
 *
 * This helps identify inline trailing comments that should move with the node
 * during sorting operations.
 *
 * @param node - The node to check for trailing comments.
 * @param source - ESLint source code object.
 * @returns The inline comment if found, null otherwise.
 */
function getCommentAfter(node, source) {
  let token = source.getTokenAfter(node, {
    filter: ({ value, type }) =>
      type !== 'Punctuator' || ![',', ';', ':'].includes(value),
    includeComments: true,
  })
  if (
    (token?.type === 'Block' || token?.type === 'Line') &&
    node.loc.end.line === token.loc.end.line
  ) {
    return token
  }
  return null
}
export { makeSingleNodeCommentAfterFixes }
