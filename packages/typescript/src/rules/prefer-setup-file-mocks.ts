import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import { isTestFile } from "./_paths.js";

type MessageIds = "preferSetupFileMocks";
type Options = readonly [];

export default ESLintUtils.RuleCreator(
  (name) => `https://github.com/sarj-ai/standards/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "prefer-setup-file-mocks",
  meta: {
    type: "suggestion",
    docs: {
      description: "Prefer defining module mocks in setup files rather than using vi.mock or jest.mock inline in test files.",
    },
    schema: [],
    messages: {
      preferSetupFileMocks:
        "Define module mocks in a setup file (e.g. vitest.setup.ts) instead of using vi.mock or jest.mock directly in test files.",
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
          node.callee.type === AST_NODE_TYPES.MemberExpression &&
          node.callee.object.type === AST_NODE_TYPES.Identifier &&
          (node.callee.object.name === "vi" || node.callee.object.name === "jest") &&
          node.callee.property.type === AST_NODE_TYPES.Identifier &&
          node.callee.property.name === "mock"
        ) {
          context.report({
            node,
            messageId: "preferSetupFileMocks",
          });
        }
      },
    };
  },
});
