import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isTestFile } from "./_paths.js";

type MessageIds = "banLooseTypeGuardsInTests";
type Options = readonly [];

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "ban-loose-type-guards-in-tests",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow loose type guards (`typeof` and `in`) in test files. Enforce Zod schemas or strict matchers for type validation.",
    },
    schema: [],
    messages: {
      banLooseTypeGuardsInTests:
        "Do not use `typeof` or `in` for type validation in tests. Use Zod schemas or strict assertion matchers instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!isTestFile(context.filename)) {
      return {};
    }

    return {
      UnaryExpression(node: TSESTree.UnaryExpression): void {
        if (node.operator === "typeof") {
          context.report({ node, messageId: "banLooseTypeGuardsInTests" });
        }
      },
      BinaryExpression(node: TSESTree.BinaryExpression): void {
        if (node.operator === "in") {
          context.report({ node, messageId: "banLooseTypeGuardsInTests" });
        }
      },
    };
  },
});
