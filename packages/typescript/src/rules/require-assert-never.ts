/**
 * @fileoverview require-assert-never — a switch over a union whose `default` does no runtime work stops being exhaustive the day the union grows.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/require-assert-never.test.ts
 */

import { type TSESLint, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "missingAssertNever";
type Options = readonly [];

/**
 * Returns true if the statement performs some runtime work. An empty statement
 * or an empty block does nothing; everything else (`return`, `throw`, `break`,
 * a function call, an `if`, ...) is treated as legitimate runtime handling of
 * the default case.
 */
const isRuntimeHandlingStatement = (statement: TSESTree.Statement): boolean => {
  if (statement.type === AST_NODE_TYPES.EmptyStatement) return false;
  if (statement.type === AST_NODE_TYPES.BlockStatement) {
    return statement.body.some(isRuntimeHandlingStatement);
  }
  return true;
};

/**
 * A `default` clause with an empty body that is followed by another `case`
 * falls through into that case, which does the real work (e.g.
 * `default: case Single: handle();`). There is nothing to assert here.
 */
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

/**
 * A `default` clause is a deliberate, documented no-op when its body is empty
 * (or an empty block) but carries a comment — e.g. `default: // do nothing`.
 * We can't distinguish a config-string switch from an exhaustive union switch
 * without type info, so a written-out intent to do nothing is honoured;
 * injecting `assertNever` there would throw at runtime. A bare empty default
 * with no comment is still flagged.
 */
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
        // No `default` at all is fine — we don't demand exhaustiveness of every
        // switch, only of those that opted into a (no-op) default.
        if (defaultIndex === -1) return;
        const defaultCase = node.cases[defaultIndex];
        if (defaultCase === undefined) return;

        // A default that does real runtime work (return a fallback, break,
        // throw, log, ...) is legitimate — don't demand assertNever there. That
        // covers the canonical `assertNever(_)` too: it is a call statement, so
        // a separate recogniser for it decided nothing this line does not
        // already decide, and no test could tell the two apart.
        if (defaultCase.consequent.some(isRuntimeHandlingStatement)) return;

        // A fallthrough default hands control to a following case, which does
        // the work — there is nothing to assert.
        if (isFallthroughDefault(node, defaultIndex)) return;

        // A deliberate, comment-documented no-op default is honoured; we can't
        // prove the discriminant is a union without type info, and injecting
        // assertNever would throw at runtime on a config-string switch.
        if (isCommentOnlyNoopDefault(defaultCase, context.sourceCode)) return;

        // Otherwise the default is a bare, undocumented no-op: flag it.
        context.report({
          node: defaultCase,
          messageId: "missingAssertNever",
        });
      },
    };
  },
});
