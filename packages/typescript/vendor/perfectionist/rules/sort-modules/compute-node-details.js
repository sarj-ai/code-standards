import { getNodeDecorators } from '../../utils/get-node-decorators.js'
import { isPropertyOrAccessorNode } from './is-property-or-accessor-node.js'
import { isArrowFunctionNode } from './is-arrow-function-node.js'
import { computeDependencies } from './compute-dependencies.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Compute details about a module-related node.
 *
 * @param params - The parameters object.
 * @param params.node - The AST node to compute details for.
 * @param params.useExperimentalDependencyDetection - Whether to use
 *   experimental dependency detection.
 * @returns The computed details about the node, such as whether it should be
 *   ignored, if a module block was found, and information about the node.
 */
function computeNodeDetails({ useExperimentalDependencyDetection, node }) {
  let selector
  let name
  let modifiers = []
  let dependencies = []
  let decorators = []
  let addSafetySemicolonWhenInline = false
  let moduleBlock = null
  let shouldPartitionAfterNode = false
  let dependencyDetection = 'soft'
  function parseNode(nodeToParse) {
    if ('declare' in nodeToParse && nodeToParse.declare) {
      modifiers.push('declare')
    }
    switch (nodeToParse.type) {
      case AST_NODE_TYPES.ExportDefaultDeclaration:
        modifiers.push('default', 'export')
        if ('decorators' in nodeToParse.declaration) {
          decorators = getNodeDecorators(nodeToParse.declaration)
        }
        parseNode(nodeToParse.declaration)
        break
      case AST_NODE_TYPES.ExportNamedDeclaration:
        if (nodeToParse.declaration) {
          if ('decorators' in nodeToParse.declaration) {
            decorators = getNodeDecorators(nodeToParse.declaration)
          }
          parseNode(nodeToParse.declaration)
        }
        modifiers.push('export')
        break
      case AST_NODE_TYPES.TSInterfaceDeclaration:
        selector = 'interface'
        ;({ name } = nodeToParse.id)
        break
      case AST_NODE_TYPES.TSTypeAliasDeclaration:
        selector = 'type'
        ;({ name } = nodeToParse.id)
        addSafetySemicolonWhenInline = true
        break
      case AST_NODE_TYPES.FunctionDeclaration:
      case AST_NODE_TYPES.TSDeclareFunction:
        selector = 'function'
        if (nodeToParse.async) {
          modifiers.push('async')
        }
        if (modifiers.includes('declare')) {
          addSafetySemicolonWhenInline = true
        }
        name = nodeToParse.id?.name
        break
      case AST_NODE_TYPES.TSModuleDeclaration:
        shouldPartitionAfterNode = true
        moduleBlock = nodeToParse.body ?? null
        break
      case AST_NODE_TYPES.VariableDeclaration:
        shouldPartitionAfterNode = true
        break
      case AST_NODE_TYPES.TSEnumDeclaration:
        selector = 'enum'
        ;({ name } = nodeToParse.id)
        dependencyDetection = 'hard'
        dependencies.push(
          ...extractDependencies(
            nodeToParse,
            useExperimentalDependencyDetection,
          ),
        )
        break
      case AST_NODE_TYPES.ClassDeclaration:
        selector = 'class'
        name = nodeToParse.id?.name
        let nodeDecorators = getNodeDecorators(nodeToParse)
        if (nodeDecorators[0]) {
          modifiers.push('decorated')
        }
        decorators = nodeDecorators
        dependencyDetection = 'hard'
        dependencies.push(
          ...extractDependencies(
            nodeToParse,
            useExperimentalDependencyDetection,
          ),
        )
    }
  }
  parseNode(node)
  if (!selector || !name) {
    return {
      shouldPartitionAfterNode,
      moduleBlock,
    }
  }
  return {
    nodeDetails: {
      addSafetySemicolonWhenInline,
      dependencyDetection,
      dependencies,
      decorators,
      modifiers,
      selector,
      name,
    },
  }
}
/**
 * Extract dependencies from an enum or class declaration.
 *
 * @deprecated - To remove when experimental dependency detection is the only
 *   option.
 * @param expression - The enum or class declaration node.
 * @param useExperimentalDependencyDetection - Whether to use experimental
 *   dependency detection.
 * @returns The list of dependencies.
 */
function extractDependencies(expression, useExperimentalDependencyDetection) {
  if (useExperimentalDependencyDetection) {
    return []
  }
  /**
   * Search static methods only if there is a static block or a static property
   * that is not an arrow function.
   */
  let searchStaticMethodsAndFunctionProperties =
    expression.type === AST_NODE_TYPES.ClassDeclaration &&
    expression.body.body.some(
      classElement =>
        classElement.type === AST_NODE_TYPES.StaticBlock ||
        (classElement.static &&
          isPropertyOrAccessorNode(classElement) &&
          !isArrowFunctionNode(classElement)),
    )
  return computeDependencies(expression, {
    searchStaticMethodsAndFunctionProperties,
    type: 'hard',
  })
}
export { computeNodeDetails }
