import {
  ESLintUtils,
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
  const callback = node.arguments.at(1);
  if (
    callback?.type === AST_NODE_TYPES.ArrowFunctionExpression ||
    callback?.type === AST_NODE_TYPES.FunctionExpression
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

      function reportCurrentRun(): void {
        const first = currentRun.at(0);
        if (currentRun.length >= 3 && first) {
          context.report({
            node: first,
            messageId: "requireParameterized",
          });
        }
      }

      for (const statement of statements) {
        if (isTestCall(statement)) {
          const bodyLen = getTestBodyStatementCount(statement.expression);
          if (bodyLen !== null) {
            if (currentRunLength === bodyLen) {
              currentRun.push(statement);
            } else {
              reportCurrentRun();
              currentRun = [statement];
              currentRunLength = bodyLen;
            }
          } else {
            reportCurrentRun();
            currentRun = [];
            currentRunLength = null;
          }
        } else {
          reportCurrentRun();
          currentRun = [];
          currentRunLength = null;
        }
      }

      reportCurrentRun();
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
