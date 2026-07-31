/**
 * @fileoverview no-async-callback-in-wait-for — an async `waitFor` callback swallows its own rejection, so the assertion inside it can never fail the test.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-async-callback-in-wait-for.test.ts
 * Evidence: https://github.com/sarj-ai/standards/blob/main/docs/rules/no-async-callback-in-wait-for.md
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "noAsyncCallbackInWaitFor";
type Options = readonly [];

export default createRule<Options, MessageIds>({
  name: "no-async-callback-in-wait-for",
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
        if (
          node.callee.type === AST_NODE_TYPES.Identifier &&
          node.callee.name === "waitFor"
        ) {
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
        }
      },
    };
  },
});
