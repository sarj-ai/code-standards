import { UnreachableCaseError } from '../../utils/unreachable-case-error.js'
import { AST_NODE_TYPES } from '../../../ast-node-types/index.cjs'
/**
 * Computes array elements for the given expression.
 *
 * @param expression - The expression to compute array elements from.
 * @returns An array of elements if the expression is an array or a new
 *   expression, otherwise null.
 */
function computeArrayElements(expression) {
  switch (expression.type) {
    case AST_NODE_TYPES.ArrayExpression:
      return expression.elements
    case AST_NODE_TYPES.NewExpression:
      if (expression.callee.type !== AST_NODE_TYPES.Identifier) {
        return null
      }
      if (expression.callee.name !== 'Array') {
        return null
      }
      return expression.arguments
    /* v8 ignore next 2 -- @preserve Exhaustive guard. */
    default:
      throw new UnreachableCaseError(expression)
  }
}
export { computeArrayElements }
