import {
  ESLintUtils,
  type TSESLint,
  type TSESTree,
  AST_NODE_TYPES,
} from "@typescript-eslint/utils";

type MessageIds = "requireParameterized";
type Options = readonly [];

function isTestCall(node: TSESTree.Statement): node is TSESTree.ExpressionStatement & { expression: TSESTree.CallExpression } {
  if (node.type !== AST_NODE_TYPES.ExpressionStatement) return false;
  const expr = node.expression;
  if (expr.type !== AST_NODE_TYPES.CallExpression) return false;
  if (expr.callee.type === AST_NODE_TYPES.Identifier) {
    return expr.callee.name === "test" || expr.callee.name === "it";
  }
  return false;
}

function getTestBodyStatementCount(node: TSESTree.CallExpression): number | null {
  const args = node.arguments;
  if (args.length < 2) return null;
  const callback = args[1];
  if (
    callback.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    callback.type === AST_NODE_TYPES.FunctionExpression
  ) {
    if (callback.body.type === AST_NODE_TYPES.BlockStatement) {
      return callback.body.body.length;
    }
  }
  return null;
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "require-parameterized-tests",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Detects repetitive sequential tests and forces the use of `test.each` or `it.each`.",
    },
    schema: [],
    messages: {
      requireParameterized:
        "These sequential tests have identical structural lengths. Consider using `test.each` or `it.each` instead of repeating them.",
    },
  },
  defaultOptions: [],
  create(context) {
    function checkStatements(statements: TSESTree.Statement[]) {
      let currentRun: TSESTree.Statement[] = [];
      let currentRunLength: number | null = null;

      for (const statement of statements) {
        if (isTestCall(statement)) {
          const bodyLen = getTestBodyStatementCount(statement.expression);
          if (bodyLen !== null) {
            if (currentRunLength === bodyLen) {
              currentRun.push(statement);
            } else {
              if (currentRun.length >= 3) {
                context.report({
                  node: currentRun[0],
                  messageId: "requireParameterized",
                });
              }
              currentRun = [statement];
              currentRunLength = bodyLen;
            }
          } else {
            if (currentRun.length >= 3) {
              context.report({
                node: currentRun[0],
                messageId: "requireParameterized",
              });
            }
            currentRun = [];
            currentRunLength = null;
          }
        } else {
          if (currentRun.length >= 3) {
            context.report({
              node: currentRun[0],
              messageId: "requireParameterized",
            });
          }
          currentRun = [];
          currentRunLength = null;
        }
      }

      if (currentRun.length >= 3) {
        context.report({
          node: currentRun[0],
          messageId: "requireParameterized",
        });
      }
    }

    return {
      BlockStatement(node) {
        checkStatements(node.body);
      },
      Program(node) {
        checkStatements(node.body);
      },
    };
  },
});
