import { buildCommonJsonSchemas } from '../utils/json-schemas/common-json-schemas.js'
import {
  LEFT,
  ORDER_ERROR,
  RIGHT,
  reportErrors,
} from '../utils/report-errors.js'
import { defaultComparatorByOptionsComputer } from '../utils/compare/default-comparator-by-options-computer.js'
import { validateCustomSortConfig } from '../utils/validate-custom-sort-config.js'
import { sortNodes } from '../utils/sort-nodes.js'
import { createNodeIndexMap } from '../utils/create-node-index-map.js'
import { makeSingleNodeCommentAfterFixes } from '../utils/make-single-node-comment-after-fixes.js'
import { createFixProvider } from '../utils/create-fix-provider.js'
import { pairwise } from '../utils/pairwise.js'
import { rangeToDiff } from '../utils/range-to-diff.js'
import { getSettings } from '../utils/get-settings.js'
import { isSortable } from '../utils/is-sortable.js'
import { complete } from '../utils/complete.js'
import { createEslintRule } from '../utils/create-eslint-rule.js'
import { isConditionExpression } from './sort-switch-case/is-condition-expression.js'
import { AST_NODE_TYPES } from '../../ast-node-types/index.cjs'
const ORDER_ERROR_ID = 'unexpectedSwitchCaseOrder'
let defaultOptions = {
  fallbackSort: { type: 'unsorted' },
  specialCharacters: 'keep',
  type: 'alphabetical',
  ignoreCase: true,
  locales: 'en-US',
  alphabet: '',
  order: 'asc',
}
var sort_switch_case_default = createEslintRule({
  create: context => ({
    SwitchStatement: switchNode => {
      if (!isSortable(switchNode.cases)) {
        return
      }
      let settings = getSettings(context.settings)
      let options = complete(context.options.at(0), settings, defaultOptions)
      let defaultComparator = defaultComparatorByOptionsComputer(options)
      validateCustomSortConfig(options)
      let { sourceCode } = context
      if (
        isConditionExpression(switchNode.discriminant) ||
        switchNode.cases.some(
          caseNode =>
            caseNode.test !== null && isConditionExpression(caseNode.test),
        )
      ) {
        return
      }
      let caseNameSortingNodeGroups = switchNode.cases.reduce(
        (accumulator, caseNode, index) => {
          if (caseNode.test) {
            accumulator.at(-1).push({
              size: rangeToDiff(caseNode.test, sourceCode),
              name: getCaseName(sourceCode, caseNode),
              partitionId: accumulator.length,
              isEslintDisabled: false,
              node: caseNode.test,
              group: 'unknown',
            })
          }
          if (
            caseNode.consequent.length > 0 &&
            index !== switchNode.cases.length - 1
          ) {
            accumulator.push([])
          }
          return accumulator
        },
        [[]],
      )
      let hasUnsortedNodes = false
      for (let caseNodesSortingNodeGroup of caseNameSortingNodeGroups) {
        let sortedCaseNameSortingNodes = sortNodes({
          comparatorByOptionsComputer: defaultComparatorByOptionsComputer,
          nodes: caseNodesSortingNodeGroup,
          ignoreEslintDisabledNodes: false,
          options,
        })
        hasUnsortedNodes ||= sortedCaseNameSortingNodes.some(
          (node, index) => node !== caseNodesSortingNodeGroup[index],
        )
        let nodeIndexMap = createNodeIndexMap(sortedCaseNameSortingNodes)
        let getCaseNameFix = createFixProvider({
          sortedNodes: sortedCaseNameSortingNodes,
          nodes: caseNodesSortingNodeGroup,
          sourceCode,
        })
        pairwise(caseNodesSortingNodeGroup, (left, right) => {
          if (!left) {
            return
          }
          if (nodeIndexMap.get(left) < nodeIndexMap.get(right)) {
            return
          }
          reportErrors({
            messageIds: [ORDER_ERROR_ID],
            getFix: getCaseNameFix,
            context,
            right,
            left,
          })
        })
      }
      let sortingNodes = switchNode.cases.map(caseNode => ({
        size: caseNode.test ? rangeToDiff(caseNode.test, sourceCode) : 7,
        name: getCaseName(sourceCode, caseNode),
        addSafetySemicolonWhenInline: true,
        isDefaultClause: !caseNode.test,
        isEslintDisabled: false,
        group: 'unknown',
        partitionId: 0,
        node: caseNode,
      }))
      let sortingNodesGroupWithDefault = reduceCaseSortingNodes(
        sortingNodes,
        caseNode => caseNode.node.consequent.length > 0,
      ).find(caseNodeGroup => caseNodeGroup.some(node => node.isDefaultClause))
      if (
        sortingNodesGroupWithDefault &&
        !sortingNodesGroupWithDefault.at(-1).isDefaultClause
      ) {
        let defaultCase = sortingNodesGroupWithDefault.find(
          node => node.isDefaultClause,
        )
        let lastCase = sortingNodesGroupWithDefault.at(-1)
        context.report({
          fix: fixer => {
            let punctuatorAfterLastCase = sourceCode.getTokenAfter(
              lastCase.node.test,
            )
            let lastCaseRange = [
              lastCase.node.range[0],
              punctuatorAfterLastCase.range[1],
            ]
            return [
              fixer.replaceText(
                defaultCase.node,
                sourceCode.text.slice(...lastCaseRange),
              ),
              fixer.replaceTextRange(
                lastCaseRange,
                sourceCode.getText(defaultCase.node),
              ),
              ...makeSingleNodeCommentAfterFixes({
                sortedNode: punctuatorAfterLastCase,
                node: defaultCase.node,
                sourceCode,
                fixer,
              }),
              ...makeSingleNodeCommentAfterFixes({
                node: punctuatorAfterLastCase,
                sortedNode: defaultCase.node,
                sourceCode,
                fixer,
              }),
            ]
          },
          data: {
            [LEFT]: defaultCase.name,
            [RIGHT]: lastCase.name,
          },
          messageId: ORDER_ERROR_ID,
          node: defaultCase.node,
        })
      }
      let sortingNodeGroupsForBlockSort = reduceCaseSortingNodes(
        sortingNodes,
        caseNode => caseHasBreakOrReturn(caseNode.node),
      )
      /**
       * If the last case does not have a return/break, leave its group at its
       * place.
       */
      let lastNodeGroup = sortingNodeGroupsForBlockSort.at(-1)
      let lastBlockCaseShouldStayInPlace = !caseHasBreakOrReturn(
        lastNodeGroup.at(-1).node,
      )
      let sortedSortingNodeGroupsForBlockSort = [
        ...sortingNodeGroupsForBlockSort,
      ]
        .toSorted((a, b) => {
          if (lastBlockCaseShouldStayInPlace) {
            if (a === lastNodeGroup) {
              return 1
            }
            /* v8 ignore if -- @preserve last element might never be b. */
            if (b === lastNodeGroup) {
              return -1
            }
          }
          if (a.some(node => node.isDefaultClause)) {
            return 1
          }
          if (b.some(node => node.isDefaultClause)) {
            return -1
          }
          return defaultComparator(a.at(0), b.at(0))
        })
        .flat()
      let sortingNodeGroupsForBlockSortFlat =
        sortingNodeGroupsForBlockSort.flat()
      let getBlockFix = createFixProvider({
        sortedNodes: sortedSortingNodeGroupsForBlockSort,
        nodes: sortingNodeGroupsForBlockSortFlat,
        sourceCode,
      })
      pairwise(sortingNodeGroupsForBlockSortFlat, (left, right) => {
        if (!left) {
          return
        }
        if (
          sortedSortingNodeGroupsForBlockSort.indexOf(left) <
          sortedSortingNodeGroupsForBlockSort.indexOf(right)
        ) {
          return
        }
        context.report({
          fix: fixer =>
            hasUnsortedNodes ?
              []
            : getBlockFix({
                hasCommentAboveMissing: false,
                fixer,
              }),
          data: {
            [RIGHT]: right.name,
            [LEFT]: left.name,
          },
          messageId: ORDER_ERROR_ID,
          node: right.node,
        })
      })
    },
  }),
  meta: {
    docs: {
      url: 'https://perfectionist.dev/rules/sort-switch-case',
      description: 'Enforce sorted switch cases.',
      recommended: true,
    },
    schema: [
      {
        properties: buildCommonJsonSchemas(),
        additionalProperties: false,
        type: 'object',
      },
    ],
    messages: { [ORDER_ERROR_ID]: ORDER_ERROR },
    type: 'suggestion',
    fixable: 'code',
  },
  defaultOptions: [defaultOptions],
  name: 'sort-switch-case',
})
/**
 * Groups consecutive switch case nodes into blocks for sorting.
 *
 * Creates partitions of case nodes where each partition ends when the
 * `endsBlock` predicate returns true (typically when a case has a break or
 * return statement).
 *
 * @param caseNodes - Array of switch case sorting nodes to partition.
 * @param endsBlock - Predicate function that determines if a case ends a block.
 * @returns A 2D array where each inner array is a sortable block of cases.
 */
function reduceCaseSortingNodes(caseNodes, endsBlock) {
  return caseNodes.reduce(
    (accumulator, caseNode, index) => {
      accumulator.at(-1).push(caseNode)
      if (endsBlock(caseNode) && index !== caseNodes.length - 1) {
        accumulator.push([])
      }
      return accumulator
    },
    [[]],
  )
}
/**
 * Extracts the name of a switch case for sorting purposes.
 *
 * For literal test values, returns the string representation of the value. For
 * the default case (null test), returns 'default'. For other expressions,
 * returns the source code text.
 *
 * @param sourceCode - The ESLint source code object.
 * @param caseNode - The switch case AST node.
 * @returns The name to use for sorting this case.
 */
function getCaseName(sourceCode, caseNode) {
  if (caseNode.test?.type === AST_NODE_TYPES.Literal) {
    return String(caseNode.test.value)
  }
  if (caseNode.test === null) {
    return 'default'
  }
  return sourceCode.getText(caseNode.test)
}
/**
 * Checks if a switch case contains a break or return statement.
 *
 * Examines the case's consequent statements, handling both direct statements
 * and statements wrapped in a block.
 *
 * @param caseNode - The switch case AST node to check.
 * @returns True if the case contains a break or return statement.
 */
function caseHasBreakOrReturn(caseNode) {
  return (
    caseNode.consequent[0]?.type === AST_NODE_TYPES.BlockStatement ?
      caseNode.consequent[0].body
    : caseNode.consequent).some(statementIsBreakOrReturn)
}
/**
 * Type guard that checks if a statement is a break or return statement.
 *
 * @param statement - The statement AST node to check.
 * @returns True if the statement is a BreakStatement or ReturnStatement.
 */
function statementIsBreakOrReturn(statement) {
  return (
    statement.type === AST_NODE_TYPES.BreakStatement ||
    statement.type === AST_NODE_TYPES.ReturnStatement
  )
}
export { sort_switch_case_default as default }
