/**
 * @fileoverview require-assert-never — a switch over a union whose `default` does no runtime work stops being exhaustive the day the union grows.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-assert-never.test.ts
 */

import { type TSESLint, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "missingAssertNever";
type Options = readonly [];

/** Empty statements and empty blocks are not runtime handling. */
const isRuntimeHandlingStatement = (statement: TSESTree.Statement): boolean => {
  if (statement.type === AST_NODE_TYPES.EmptyStatement) return false;
  if (statement.type === AST_NODE_TYPES.BlockStatement) {
    return statement.body.some(isRuntimeHandlingStatement);
  }
  return true;
};

/** An empty non-final default falls through to a case that handles it. */
const isFallthroughDefault = (
  node: TSESTree.SwitchStatement,
  defaultIndex: number,
): boolean => {
  const defaultCase = node.cases[defaultIndex];
  return (
    defaultCase !== undefined &&
    defaultCase.consequent.length === 0 &&
    defaultIndex < node.cases.length - 1
  );
};

/** Honor a comment that makes an empty default an intentional no-op. */
const isCommentOnlyNoopDefault = (
  defaultCase: TSESTree.SwitchCase,
  sourceCode: Readonly<TSESLint.SourceCode>,
): boolean => {
  if (defaultCase.consequent.length === 0) {
    const defaultToken = sourceCode.getFirstToken(defaultCase);
    const colonToken = defaultToken
      ? sourceCode.getTokenAfter(defaultToken)
      : null;
    return (
      colonToken !== null && sourceCode.getCommentsAfter(colonToken).length > 0
    );
  }
  const only = defaultCase.consequent[0];
  if (
    only !== undefined &&
    defaultCase.consequent.length === 1 &&
    only.type === AST_NODE_TYPES.BlockStatement &&
    only.body.length === 0
  ) {
    return sourceCode.getCommentsInside(only).length > 0;
  }
  return false;
};

export default createRule<Options, MessageIds>({
  name: "require-assert-never",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require an exhaustive-style switch whose `default` case does no runtime work to call `assertNever(_)` so that discriminated unions are exhaustively checked at compile time. Switches with a legitimate runtime default (a reducer's `return state`, an HTTP-status `return fallback()`, a `break`, a `throw`, etc.) are left alone.",
    },
    schema: [],
    messages: {
      missingAssertNever:
        "Empty switch `default` case — add runtime handling or call `assertNever()` so the discriminated union is exhaustively checked at compile time.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      SwitchStatement(node: TSESTree.SwitchStatement): void {
        const defaultIndex = node.cases.findIndex(
          (caseNode) => caseNode.test === null,
        );
        // Only present no-op defaults opt into this syntactic check.
        if (defaultIndex === -1) return;
        const defaultCase = node.cases[defaultIndex];
        if (defaultCase === undefined) return;

        // Any runtime work, including assertNever(), handles the default.
        if (defaultCase.consequent.some(isRuntimeHandlingStatement)) return;

        // A non-final empty default is handled by its following case.
        if (isFallthroughDefault(node, defaultIndex)) return;

        // Comments distinguish deliberate no-ops without requiring type info.
        if (isCommentOnlyNoopDefault(defaultCase, context.sourceCode)) return;

        context.report({
          node: defaultCase,
          messageId: "missingAssertNever",
        });
      },
    };
  },
});
