import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

export default ESLintUtils.RuleCreator.withoutDocs({
  meta: {
    type: "suggestion",
    docs: {
      description: "Replace multiple sequential assertions with a single toMatchObject or toStrictEqual",
    },
    fixable: "code",
    messages: {
      combineAssertions: "Combine multiple sequential assertions on the same object into a single toMatchObject or toStrictEqual",
    },
    schema: [],
  },
  defaultOptions: [],
  create(context) {
    function checkBody(body: TSESTree.Statement[]) {
      let currentObject: TSESTree.Expression | null = null;
      let sequence: TSESTree.ExpressionStatement[] = [];

      function getExpectObject(expr: TSESTree.Expression): TSESTree.Expression | null {
        if (
          expr.type === AST_NODE_TYPES.CallExpression &&
          expr.callee.type === AST_NODE_TYPES.MemberExpression &&
          expr.callee.object.type === AST_NODE_TYPES.CallExpression &&
          expr.callee.object.callee.type === AST_NODE_TYPES.Identifier &&
          expr.callee.object.callee.name === "expect" &&
          expr.callee.object.arguments.length === 1
        ) {
          const arg = expr.callee.object.arguments.at(0);
          if (arg?.type === AST_NODE_TYPES.MemberExpression) {
            return arg.object;
          }
        }
        return null;
      }
      
      function reportSequence() {
        const first = sequence.at(0);
        if (sequence.length > 1 && first) {
          context.report({
            node: first,
            messageId: "combineAssertions",
            fix(fixer) {
              if (!currentObject) return null;
              const objectText = context.sourceCode.getText(currentObject);
              const props = sequence.map(stmt => {
                if (
                  stmt.expression.type !== AST_NODE_TYPES.CallExpression ||
                  stmt.expression.callee.type !== AST_NODE_TYPES.MemberExpression ||
                  stmt.expression.callee.object.type !== AST_NODE_TYPES.CallExpression
                ) {
                  return null;
                }

                const actual = stmt.expression.callee.object.arguments.at(0);
                const expected = stmt.expression.arguments.at(0);
                if (
                  actual?.type === AST_NODE_TYPES.MemberExpression &&
                  actual.property.type === AST_NODE_TYPES.Identifier &&
                  expected
                ) {
                  const propName = actual.property.name;
                  const valText = context.sourceCode.getText(expected);
                  return `${propName}: ${valText}`;
                }
                return null;
              });
              if (props.some(p => p === null)) return null;
              const replacement = `expect(${objectText}).toMatchObject({ ${props.join(", ")} });`;
              
              return [
                fixer.replaceText(first, replacement),
                ...sequence.slice(1).map(stmt => fixer.remove(stmt))
              ];
            }
          });
        }
      }

      for (const statement of body) {
        if (statement.type === AST_NODE_TYPES.ExpressionStatement) {
          const obj = getExpectObject(statement.expression);
          if (obj && currentObject && context.sourceCode.getText(obj) === context.sourceCode.getText(currentObject)) {
            sequence.push(statement);
          } else {
            reportSequence();
            if (obj) {
              currentObject = obj;
              sequence = [statement];
            } else {
              currentObject = null;
              sequence = [];
            }
          }
        } else {
          reportSequence();
          currentObject = null;
          sequence = [];
        }
      }
      reportSequence();
    }
    
    return {
      BlockStatement(node) {
        checkBody(node.body);
      },
      Program(node) {
        checkBody(node.body);
      }
    };
  },
});
