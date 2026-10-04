import { isSortable } from '../../utils/is-sortable.js'
import { OverloadSignatureGroup } from '../../utils/overload-signature/overload-signature-group.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Returns a list of groups of overload signatures.
 *
 * @param nodes - The nodes to process.
 * @returns A list of overload signature groups.
 */
function computeOverloadSignatureGroups(nodes) {
  let functionDetailsByName = /* @__PURE__ */ new Map()
  for (let node of nodes) {
    let functionDetails = computeNodeFunctionDetails(node)
    if (!functionDetails) {
      continue
    }
    let functionDetailsArray = functionDetailsByName.get(functionDetails.name)
    if (!functionDetailsArray) {
      functionDetailsArray = []
      functionDetailsByName.set(functionDetails.name, functionDetailsArray)
    }
    functionDetailsArray.push({
      ...functionDetails,
      node,
    })
  }
  let overloadSignatureGroups = []
  for (let functionDetailsArray of functionDetailsByName.values()) {
    if (isSortable(functionDetailsArray)) {
      overloadSignatureGroups.push(
        buildOverloadSignatureGroup(functionDetailsArray),
      )
    }
  }
  return overloadSignatureGroups
}
function computeNodeFunctionDetails(node) {
  let currentNode = node
  while (
    currentNode.type === AST_NODE_TYPES.ExportDefaultDeclaration ||
    currentNode.type === AST_NODE_TYPES.ExportNamedDeclaration
  ) {
    /* v8 ignore start -- @preserve Unsure how we can reach that case */
    if (!currentNode.declaration) {
      return null
    }
    /* v8 ignore stop -- @preserve Unsure how we can reach that case */
    currentNode = currentNode.declaration
  }
  switch (currentNode.type) {
    case AST_NODE_TYPES.FunctionDeclaration:
    case AST_NODE_TYPES.TSDeclareFunction:
      return computeFunctionDetails(currentNode)
    default:
      return null
  }
  function computeFunctionDetails(functionNode) {
    /* v8 ignore if -- @preserve Unsure how we can reach that case */
    if (!functionNode.id) {
      return null
    }
    return {
      isImplementation:
        functionNode.type === AST_NODE_TYPES.FunctionDeclaration,
      name: functionNode.id.name,
    }
  }
}
function buildOverloadSignatureGroup(functionDetailsArray) {
  let implementation = (
    functionDetailsArray.find(isFunctionImplementation) ??
    functionDetailsArray.at(-1)
  ).node
  let overloadSignatures = functionDetailsArray
    .filter(functionDetails => !isFunctionImplementation(functionDetails))
    .map(functionDetails => functionDetails.node)
  return new OverloadSignatureGroup({
    overloadSignatures,
    implementation,
  })
  function isFunctionImplementation(functionDetails) {
    return functionDetails.isImplementation
  }
}
export { computeOverloadSignatureGroups }
