import { computeParentNodesWithTypes } from '../../../utils/compute-parent-nodes-with-types.js'
import { UnreachableCaseError } from '../../../utils/unreachable-case-error.js'
import { getNodeDecorators } from '../../../utils/get-node-decorators.js'
import { AST_NODE_TYPES } from '../../../../ast-node-types/index.cjs'
function isIdentifierInDecoratorMetadataTypePosition({
  sortingNodes,
  identifier,
}) {
  let { parent } = identifier
  if (
    parent.type !== AST_NODE_TYPES.TSTypeReference ||
    parent.typeName !== identifier
  ) {
    return false
  }
  if (isLocalNonClassReference(sortingNodes, identifier)) {
    return false
  }
  let typeAnnotationHost = computeTypeAnnotationHost(parent)
  if (!typeAnnotationHost) {
    return false
  }
  switch (typeAnnotationHost.type) {
    case AST_NODE_TYPES.TSAbstractPropertyDefinition:
    case AST_NODE_TYPES.PropertyDefinition:
    case AST_NODE_TYPES.AccessorProperty:
      return getNodeDecorators(typeAnnotationHost).length > 0
    case AST_NODE_TYPES.FunctionExpression: {
      let methodDefinition = typeAnnotationHost.parent
      if (methodDefinition.type !== AST_NODE_TYPES.MethodDefinition) {
        return false
      }
      if (methodDefinition.kind === 'set') {
        return getNodeDecorators(methodDefinition).length > 0
      }
      if (
        methodDefinition.value.params.some(
          parameter => getNodeDecorators(parameter).length > 0,
        )
      ) {
        return true
      }
      switch (methodDefinition.kind) {
        case 'constructor':
          return getNodeDecorators(methodDefinition.parent.parent).length > 0
        case 'method':
        case 'get':
          return getNodeDecorators(methodDefinition).length > 0
        /* v8 ignore next 2 -- @preserve Exhaustive guard. */
        default:
          throw new UnreachableCaseError(methodDefinition.kind)
      }
    }
    default:
      return false
  }
}
function computeTypeAnnotationHost(typeReference) {
  let annotation = typeReference.parent
  if (
    annotation.type === AST_NODE_TYPES.TSArrayType &&
    annotation.parent.type === AST_NODE_TYPES.TSTypeAnnotation &&
    annotation.parent.parent.type === AST_NODE_TYPES.RestElement
  ) {
    annotation = annotation.parent
  }
  if (annotation.type !== AST_NODE_TYPES.TSTypeAnnotation) {
    return null
  }
  return (
    computeParentNodesWithTypes({
      allowedTypes: [
        AST_NODE_TYPES.Identifier,
        AST_NODE_TYPES.ObjectPattern,
        AST_NODE_TYPES.ArrayPattern,
        AST_NODE_TYPES.RestElement,
        AST_NODE_TYPES.AssignmentPattern,
        AST_NODE_TYPES.TSParameterProperty,
      ],
      consecutiveOnly: true,
      node: annotation,
      maxParent: null,
    }).at(-1)?.parent ?? annotation.parent
  )
}
function isLocalNonClassReference(sortingNodes, identifier) {
  let matchingSortingNode = sortingNodes.find(
    sortingNode => sortingNode.name === identifier.name,
  )
  if (!matchingSortingNode) {
    return false
  }
  return (
    (matchingSortingNode.node.type === AST_NODE_TYPES.ExportNamedDeclaration ?
      matchingSortingNode.node.declaration
    : matchingSortingNode.node
    )?.type !== AST_NODE_TYPES.ClassDeclaration
  )
}
export { isIdentifierInDecoratorMetadataTypePosition }
