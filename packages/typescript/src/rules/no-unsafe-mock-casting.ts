import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { isGeneratedFile } from "./_paths.js";

type MessageIds = "unsafeMockCast";

function isMockTypeReference(node: TSESTree.TypeNode): boolean {
  if (node.type !== AST_NODE_TYPES.TSTypeReference) {
    return false;
  }
  
  const typeName = node.typeName;
  
  if (typeName.type === AST_NODE_TYPES.Identifier) {
    const name = typeName.name;
    return name === "Mock" || name === "MockInstance" || name === "SpyInstance";
  }
  
  if (typeName.type === AST_NODE_TYPES.TSQualifiedName) {
    const rightName = typeName.right.name;
    return rightName === "Mock" || rightName === "MockInstance" || rightName === "SpyInstance";
  }
  
  return false;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<[], MessageIds>({
  name: "no-unsafe-mock-casting",
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow casting to mock types like `jest.Mock` or `vi.Mock`. Use `vi.mocked()` or `jest.mocked()` instead.",
    },
    schema: [],
    messages: {
      unsafeMockCast:
        "Do not cast to a Mock type. Use `vi.mocked(fn)` or `jest.mocked(fn)` instead to preserve type safety.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }

    function checkAssertion(
      node: TSESTree.TSAsExpression | TSESTree.TSTypeAssertion,
    ): void {
      if (isMockTypeReference(node.typeAnnotation)) {
        context.report({ node, messageId: "unsafeMockCast" });
      }
    }

    return {
      TSAsExpression: checkAssertion,
      TSTypeAssertion: checkAssertion,
    };
  },
});
