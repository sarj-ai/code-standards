import { computeNodesInCircularDependencies } from './compute-nodes-in-circular-dependencies.js'
import { isNodeDependentOnOtherNode } from './is-node-dependent-on-other-node.js'
/**
 * Returns nodes topologically sorted by their dependencies.
 *
 * @param nodes - The nodes to sort.
 * @param [extraOptions] - Additional sorting options.
 * @returns The nodes sorted in topological order.
 */
/**
 * Sorts nodes using topological sorting based on their dependencies.
 *
 * Implements a depth-first search algorithm to ensure that dependencies appear
 * before the nodes that depend on them. This is important for maintaining
 * logical order in code where some elements reference others.
 *
 * Nodes involved in circular dependencies are excluded from dependency-based
 * ordering and retain their original relative positions.
 *
 * @example
 *
 * ```ts
 * // TypeScript interfaces with inheritance
 * const nodes = [
 *   {
 *     name: 'AdminUser',
 *     dependencies: ['AdminUser'],
 *     dependencyNames: ['User'],
 *   },
 *   { name: 'User', dependencies: ['User'], dependencyNames: [] },
 *   {
 *     name: 'GuestUser',
 *     dependencies: ['GuestUser'],
 *     dependencyNames: ['User'],
 *   },
 * ]
 * sortNodesByDependencies(nodes)
 * // Returns: [User, AdminUser, GuestUser]
 * // User must come first as others depend on it
 * ```
 *
 * @example
 *
 * ```ts
 * // React components with hook dependencies
 * const nodes = [
 *   {
 *     name: 'MyComponent',
 *     dependencies: ['MyComponent'],
 *     dependencyNames: ['useAuth', 'useData'],
 *   },
 *   {
 *     name: 'useData',
 *     dependencies: ['useData'],
 *     dependencyNames: ['useApi'],
 *   },
 *   { name: 'useApi', dependencies: ['useApi'], dependencyNames: [] },
 *   { name: 'useAuth', dependencies: ['useAuth'], dependencyNames: [] },
 * ]
 * sortNodesByDependencies(nodes)
 * // Returns: [useApi, useData, useAuth, MyComponent]
 * // Hooks are ordered by their dependency chain
 * ```
 *
 * @example
 *
 * ```ts
 * // Object properties with computed values
 * const config = {
 *   baseUrl: 'https://api.example.com',
 *   apiUrl: `${this.baseUrl}/v1`, // Depends on baseUrl
 *   authUrl: `${this.apiUrl}/auth`, // Depends on apiUrl
 *   headers: {
 *     'API-Key': this.apiKey, // Depends on apiKey
 *   },
 *   apiKey: process.env.API_KEY,
 * }
 * // After sorting: baseUrl, apiKey, apiUrl, authUrl, headers
 * ```
 *
 * @template T - Type of sorting node with dependencies.
 * @param nodes - Array of nodes to sort by dependencies.
 * @param extraOptions - Additional sorting options.
 * @returns Topologically sorted array of nodes.
 */
function sortNodesByDependencies(nodes, extraOptions) {
  let nodesInCircularDependencies = computeNodesInCircularDependencies(nodes)
  let result = []
  let visitedNodes = /* @__PURE__ */ new Set()
  /**
   * Recursively visits nodes in dependency order (depth-first).
   *
   * Ensures all dependencies of a node are visited and added to the result
   * before the node itself. This creates the correct topological ordering.
   *
   * @param sortingNode - The node to visit.
   */
  function visitNode(sortingNode) {
    if (visitedNodes.has(sortingNode)) {
      return
    }
    let dependentNodes = nodes
      .filter(node => !nodesInCircularDependencies.has(node))
      .filter(node => isNodeDependentOnOtherNode(node, sortingNode))
    for (let dependentNode of dependentNodes) {
      if (
        !extraOptions.ignoreEslintDisabledNodes ||
        !dependentNode.isEslintDisabled
      ) {
        visitNode(dependentNode)
      }
    }
    visitedNodes.add(sortingNode)
    result.push(sortingNode)
  }
  for (let node of nodes) {
    visitNode(node)
  }
  return result
}
export { sortNodesByDependencies }
