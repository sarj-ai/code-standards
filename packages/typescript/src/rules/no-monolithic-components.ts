import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "monolithicComponent";
type Options = readonly [
  {
    maxLines?: number;
  }?,
];

const DEFAULT_MAX_LINES = 250;

function isPascalCase(name: string): boolean {
  return /^[A-Z][a-zA-Z0-9]*$/.test(name);
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "no-monolithic-components",
  meta: {
    type: "suggestion",
    docs: {
      description: "Prevent React component functions or classes from exceeding a certain line count.",
    },
    schema: [
      {
        type: "object",
        additionalProperties: false,
        properties: {
          maxLines: {
            type: "number",
          },
        },
      },
    ],
    messages: {
      monolithicComponent: "React component {{name}} exceeds {{maxLines}} lines of code ({{lines}} lines). Consider breaking it down into smaller components.",
    },
  },
  defaultOptions: [{}],
  create(context, [optionsArg]) {
    const maxLines = optionsArg?.maxLines ?? DEFAULT_MAX_LINES;

    function checkComponent(
      node: TSESTree.FunctionDeclaration | TSESTree.FunctionExpression | TSESTree.ArrowFunctionExpression | TSESTree.ClassDeclaration | TSESTree.ClassExpression,
      name: string
    ) {
      if (!isPascalCase(name)) {
        return;
      }
      
      const lines = node.loc.end.line - node.loc.start.line + 1;
      if (lines > maxLines) {
        context.report({
          node,
          messageId: "monolithicComponent",
          data: {
            name,
            maxLines,
            lines,
          },
        });
      }
    }

    return {
      FunctionDeclaration(node) {
        if (node.id) {
          checkComponent(node, node.id.name);
        }
      },
      FunctionExpression(node) {
        if (node.parent?.type === "VariableDeclarator" && node.parent.id.type === "Identifier") {
          checkComponent(node, node.parent.id.name);
        }
      },
      ArrowFunctionExpression(node) {
        if (node.parent?.type === "VariableDeclarator" && node.parent.id.type === "Identifier") {
          checkComponent(node, node.parent.id.name);
        }
      },
      ClassDeclaration(node) {
        if (node.id) {
          checkComponent(node, node.id.name);
        }
      },
      ClassExpression(node) {
        if (node.parent?.type === "VariableDeclarator" && node.parent.id.type === "Identifier") {
          checkComponent(node, node.parent.id.name);
        }
      }
    };
  },
});
