/**
 * @fileoverview no-async-callback-in-wait-for — an async `waitFor` callback swallows its own rejection, so the assertion inside it can never fail the test.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-async-callback-in-wait-for.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noAsyncCallbackInWaitFor";
type Options = readonly [];

export const noAsyncCallbackInWaitForDocumentation = {
  summary: "Disallow async callbacks in `waitFor` to prevent swallowed promise rejections.",
  rationale:
    "`waitFor` retries synchronous assertions; an async callback changes that contract and can hide a rejected assertion promise.",
  remediation: "Remove `async` and keep the assertions inside `waitFor` synchronous.",
  category: "testing",
  aliases: ["no-async-callback-in-waitfor"],
  limitations: [
    "The rule checks inline first-argument callbacks to bare or non-computed `.waitFor` calls in test files.",
  ],
  examples: [
    {
      id: "synchronous-wait-for-callback",
      title: "waitFor retries a synchronous assertion",
      outcome: "no-match",
      files: [{ path: "src/component.test.ts", source: "it('works', async () => { await waitFor(() => expect(foo).toBe(true)); });" }],
      focusPath: "src/component.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "async-wait-for-callback",
      title: "waitFor receives an async callback",
      outcome: "match",
      files: [{ path: "src/component.test.ts", source: "it('fails', async () => { await waitFor(async () => expect(foo).toBe(true)); });" }],
      focusPath: "src/component.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

/** Match bare and non-computed member calls; the receiver does not change the polling contract. */
const isWaitForCallee = (callee: TSESTree.CallExpression["callee"]): boolean => {
  if (callee.type === AST_NODE_TYPES.Identifier) return callee.name === "waitFor";
  return (
    callee.type === AST_NODE_TYPES.MemberExpression &&
    !callee.computed &&
    callee.property.type === AST_NODE_TYPES.Identifier &&
    callee.property.name === "waitFor"
  );
};

export default createRule<Options, MessageIds>({
  name: "no-async-callback-in-wait-for",
  documentation: noAsyncCallbackInWaitForDocumentation,
  meta: {
    type: "problem",
    docs: {
      description: "Disallow async callbacks in `waitFor` to prevent swallowed promise rejections.",
    },
    schema: [],
    messages: {
      noAsyncCallbackInWaitFor:
        "The callback to `waitFor` should not be async. It expects synchronous assertions and runs the callback repeatedly.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }
    return {
      CallExpression(node: TSESTree.CallExpression) {
        if (!isWaitForCallee(node.callee)) return;
        const callback = node.arguments[0];
        if (
          callback &&
          (callback.type === AST_NODE_TYPES.ArrowFunctionExpression ||
            callback.type === AST_NODE_TYPES.FunctionExpression) &&
          callback.async
        ) {
          context.report({
            node: callback,
            messageId: "noAsyncCallbackInWaitFor",
          });
        }
      },
    };
  },
});
