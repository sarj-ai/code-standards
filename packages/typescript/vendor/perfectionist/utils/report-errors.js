const NODE_DEPENDENT_ON_RIGHT = 'nodeDependentOnRight'
const RIGHT = 'right'
const RIGHT_GROUP = 'rightGroup'
const LEFT = 'left'
const LEFT_GROUP = 'leftGroup'
const MISSED_COMMENT_ABOVE = 'missedCommentAbove'
const ORDER_ERROR = `Expected "{{${RIGHT}}}" to come before "{{${LEFT}}}".`
const DEPENDENCY_ORDER_ERROR = `Expected dependency "{{${RIGHT}}}" to come before "{{${NODE_DEPENDENT_ON_RIGHT}}}".`
const GROUP_ORDER_ERROR = `Expected "{{${RIGHT}}}" ({{${RIGHT_GROUP}}}) to come before "{{${LEFT}}}" ({{${LEFT_GROUP}}}).`
const EXTRA_SPACING_ERROR = `Extra spacing between "{{${LEFT}}}" and "{{${RIGHT}}}".`
const MISSED_SPACING_ERROR = `Missed spacing between "{{${LEFT}}}" and "{{${RIGHT}}}".`
const MISSED_COMMENT_ABOVE_ERROR = `Missed comment "{{${MISSED_COMMENT_ABOVE}}}" above "{{${RIGHT}}}".`
/**
 * Reports ESLint errors with contextual data and auto-fix support.
 *
 * Generates ESLint error reports for each provided message ID, including:
 *
 * - Contextual data for error messages (element names, groups, dependencies)
 * - Auto-fix function that applies all necessary corrections
 * - Node location for error highlighting.
 *
 * The function supports dynamic message templates with placeholders that are
 * replaced with actual values:
 *
 * - {{left}} / {{right}} - Element names in the comparison
 * - {{leftGroup}} / {{rightGroup}} - Group names
 * - {{nodeDependentOnRight}} - Name of dependent element
 * - {{missedCommentAbove}} - Missing comment text.
 *
 * @example
 *
 * ```ts
 * // Reporting import order violation
 * reportErrors({
 *   messageIds: ['unexpectedOrder'],
 *   left: { name: 'useState', group: 'react' },
 *   right: { name: 'React', group: 'react' },
 *   // Error: "Expected 'React' to come before 'useState'"
 * })
 * ```
 *
 * @example
 *
 * ```ts
 * // Reporting dependency violation in TypeScript interfaces
 * reportErrors({
 * messageIds: ['unexpectedDependencyOrder'],
 * right: { name: 'User', ... },
 * firstUnorderedNodeDependentOnRight: { name: 'AdminUser extends User', ... },
 * // Error: "Expected 'User' to come before 'AdminUser extends User' due to dependency"
 * });
 * ```
 *
 * @example
 *
 * ```ts
 * // Reporting missing newlines between import groups
 * reportErrors({
 *   messageIds: ['missedSpacingBetweenMembers'],
 *   left: { name: 'React', group: 'external' },
 *   right: { name: './utils', group: 'internal' },
 *   // Error: "Expected newline between external and internal imports"
 * })
 * ```
 *
 * @template MessageIds - Union of message IDs.
 * @template T - Type of sorting node.
 * @param params - Parameters for error reporting.
 */
function reportErrors({
  firstUnorderedNodeDependentOnRight,
  commentAboveMissing,
  messageIds,
  context,
  getFix,
  right,
  left,
}) {
  for (let messageId of messageIds) {
    context.report({
      data: {
        [NODE_DEPENDENT_ON_RIGHT]: firstUnorderedNodeDependentOnRight?.name,
        [MISSED_COMMENT_ABOVE]: commentAboveMissing,
        [LEFT]: toSingleLine(left?.name ?? ''),
        [RIGHT]: toSingleLine(right.name),
        [RIGHT_GROUP]: right.group,
        [LEFT_GROUP]: left?.group,
      },
      fix: fixer =>
        getFix({
          hasCommentAboveMissing: !!commentAboveMissing,
          fixer,
        }),
      node: right.node,
      messageId,
    })
  }
}
/**
 * Converts multi-line strings to single-line for error messages.
 *
 * Normalizes element names that may span multiple lines (like template
 * literals, multi-line imports, or complex expressions) into a single line
 * format suitable for error messages.
 *
 * @example
 *
 * ```ts
 * toSingleLine(`
 * import {
 * Component
 * } from 'react'
 * `)
 * // Returns: "import { Component } from 'react'"
 * ```
 *
 * @param string - Multi-line string to normalize.
 * @returns Single-line string with normalized whitespace.
 */
function toSingleLine(string) {
  return string.replaceAll(/\s{2,}/gu, ' ').trim()
}
export {
  DEPENDENCY_ORDER_ERROR,
  EXTRA_SPACING_ERROR,
  GROUP_ORDER_ERROR,
  LEFT,
  MISSED_COMMENT_ABOVE_ERROR,
  MISSED_SPACING_ERROR,
  ORDER_ERROR,
  RIGHT,
  reportErrors,
}
