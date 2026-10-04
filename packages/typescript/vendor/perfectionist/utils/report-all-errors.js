import { reportErrors } from './report-errors.js'
import { computeNodesInCircularDependencies } from './compute-nodes-in-circular-dependencies.js'
import { isNodeDependentOnOtherNode } from './is-node-dependent-on-other-node.js'
import { getGroupIndex } from './get-group-index.js'
import { getCommentAboveThatShouldExist } from './get-comment-above-that-should-exist.js'
import { getNewlinesBetweenErrors } from './get-newlines-between-errors.js'
import { createNodeIndexMap } from './create-node-index-map.js'
import { createFixProvider } from './create-fix-provider.js'
import { pairwise } from './pairwise.js'
/**
 * Detects and reports all sorting violations.
 *
 * Performs a complete analysis of sorting errors including:
 *
 * - Order violations (elements in wrong positions)
 * - Group order violations (elements in wrong groups)
 * - Dependency violations (dependent elements before their dependencies)
 * - Spacing issues (missing or extra newlines between groups)
 * - Missing comment separators above groups.
 *
 * The function uses pairwise comparison to check each adjacent pair of nodes
 * and accumulates all applicable error messages for each violation.
 *
 * @example
 *
 * ```ts
 * // Import statements with violations
 * import { useState } from 'react' // Should be after React import
 * import React from 'react' // Group order violation
 * import type { User } from './types' // Missing newline between groups
 * ```
 *
 * @example
 *
 * ```ts
 * // Object properties with dependency violation
 * const config = {
 *   apiUrl: process.env.API_URL,
 *   baseUrl: this.apiUrl + '/v1', // Depends on apiUrl
 *   timeout: 5000,
 *   headers: {
 *     Authorization: this.token, // Should be after token definition
 *   },
 *   token: getAuthToken(),
 * }
 * ```
 *
 * @template MessageIds - Union of available message IDs.
 * @template T - Type of sorting node.
 * @param params - Parameters for error detection and reporting.
 */
function reportAllErrors({
  ignoreFirstNodeHighestBlockComment,
  sortNodesExcludingEslintDisabled,
  newlinesBetweenValueGetter,
  availableMessageIds,
  context,
  options,
  nodes,
}) {
  let { sourceCode } = context
  let sortedNodes = sortNodesExcludingEslintDisabled(false)
  let sortedNodesExcludingEslintDisabled =
    sortNodesExcludingEslintDisabled(true)
  let nodeIndexMap = createNodeIndexMap(sortedNodes)
  /**
   * Only rules that report dependency violations pass nodes carrying
   * dependencies, so the dependency shape is used behind
   * `unexpectedDependencyOrder` alone.
   */
  let nodesWithDependencies = nodes
  let nodesInCircularDependencies =
    availableMessageIds.unexpectedDependencyOrder ?
      computeNodesInCircularDependencies(nodesWithDependencies)
    : /* @__PURE__ */ new Set()
  let getFix = createFixProvider({
    sortedNodes: sortedNodesExcludingEslintDisabled,
    ignoreFirstNodeHighestBlockComment,
    newlinesBetweenValueGetter,
    sourceCode,
    options,
    nodes,
  })
  pairwise(nodes, (left, right) => {
    let leftInfo =
      left ?
        {
          groupIndex: getGroupIndex(options.groups, left),
          index: nodeIndexMap.get(left),
        }
      : null
    let rightGroupIndex = getGroupIndex(options.groups, right)
    let rightIndex = nodeIndexMap.get(right)
    let indexOfRightExcludingEslintDisabled =
      sortedNodesExcludingEslintDisabled.indexOf(right)
    let messageIds = []
    let firstUnorderedNodeDependentOnRight
    if (availableMessageIds.unexpectedDependencyOrder) {
      firstUnorderedNodeDependentOnRight = getFirstUnorderedNodeDependentOn({
        node: right,
        nodes: nodesWithDependencies,
        nodesInCircularDependencies,
      })
    }
    if (
      leftInfo &&
      (firstUnorderedNodeDependentOnRight ||
        leftInfo.index > rightIndex ||
        (left?.isEslintDisabled &&
          leftInfo.index >= indexOfRightExcludingEslintDisabled))
    ) {
      if (firstUnorderedNodeDependentOnRight) {
        messageIds.push(availableMessageIds.unexpectedDependencyOrder)
      } else {
        messageIds.push(
          (
            leftInfo.groupIndex === rightGroupIndex ||
              !availableMessageIds.unexpectedGroupOrder
          ) ?
            availableMessageIds.unexpectedOrder
          : availableMessageIds.unexpectedGroupOrder,
        )
      }
    }
    if (
      left &&
      availableMessageIds.missedSpacingBetweenMembers &&
      availableMessageIds.extraSpacingBetweenMembers
    ) {
      messageIds.push(
        ...getNewlinesBetweenErrors({
          options: {
            ...options,
            newlinesBetween: options.newlinesBetween,
          },
          missedSpacingError: availableMessageIds.missedSpacingBetweenMembers,
          extraSpacingError: availableMessageIds.extraSpacingBetweenMembers,
          leftGroupIndex: leftInfo.groupIndex,
          newlinesBetweenValueGetter,
          rightGroupIndex,
          sourceCode,
          right,
          left,
        }),
      )
    }
    let commentAboveMissing
    if (availableMessageIds.missedCommentAbove) {
      let commentAboveThatShouldExist = getCommentAboveThatShouldExist({
        leftGroupIndex: leftInfo?.groupIndex ?? null,
        sortingNode: right,
        rightGroupIndex,
        sourceCode,
        options,
      })
      if (commentAboveThatShouldExist && !commentAboveThatShouldExist.exists) {
        commentAboveMissing = commentAboveThatShouldExist.comment
        messageIds.push(availableMessageIds.missedCommentAbove)
      }
    }
    reportErrors({
      firstUnorderedNodeDependentOnRight,
      commentAboveMissing,
      messageIds,
      context,
      getFix,
      right,
      left,
    })
  })
}
/**
 * Finds the first node that depends on the given node but appears before it.
 *
 * Detects dependency violations where a dependent element appears before its
 * dependency in the current order. This is important for maintaining logical
 * ordering in code where some elements reference others.
 *
 * Nodes in circular dependencies are excluded from this check as they cannot be
 * properly ordered.
 *
 * @example
 *
 * ```ts
 * // TypeScript interface extending another
 * interface AdminUser extends User {
 *   // This depends on User
 *   permissions: string[]
 * }
 * interface User {
 *   // But User appears after AdminUser
 *   id: string
 *   name: string
 * }
 * // Returns: AdminUser node (appears before its dependency).
 * ```
 *
 * @template T - Type of sorting node with dependencies.
 * @param params - Parameters for finding dependent nodes.
 * @param params.nodesInCircularDependencies - Set of nodes in circular
 *   dependencies.
 * @param params.nodes - All nodes in current order.
 * @param params.node - The node to check for dependents.
 * @returns First dependent node appearing before its dependency, or undefined.
 */
function getFirstUnorderedNodeDependentOn({
  nodesInCircularDependencies,
  nodes,
  node,
}) {
  return nodes
    .filter(
      currentlyOrderedNode =>
        !nodesInCircularDependencies.has(currentlyOrderedNode) &&
        isNodeDependentOnOtherNode(node, currentlyOrderedNode),
    )
    .find(firstNodeDependentOnNode => {
      let currentIndexOfNode = nodes.indexOf(node)
      return nodes.indexOf(firstNodeDependentOnNode) < currentIndexOfNode
    })
}
export { reportAllErrors }
