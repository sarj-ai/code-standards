/**
 * Returns if a node is on a single line.
 *
 * @param node - The node to check.
 * @returns True if the node is on a single line, false otherwise.
 */
function isNodeOnSingleLine(node) {
  return node.loc.start.line === node.loc.end.line
}
export { isNodeOnSingleLine }
