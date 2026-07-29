import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "noAsyncCallbackInWaitFor";
type Options = readonly [];

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-async-callback-in-waitfor",
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
