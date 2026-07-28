import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

type MessageIds = "missingInteractiveStates";
type Options = readonly [];

const INTERACTIVE_ELEMENTS = new Set(["button", "input", "select", "textarea"]);

function extractStrings(node: TSESTree.Node): string[] {
  if (node.type === AST_NODE_TYPES.Literal && typeof node.value === "string") {
    return [node.value];
  }
  if (node.type === AST_NODE_TYPES.TemplateLiteral) {
    return node.quasis.map(q => q.value.raw);
  }
  if (node.type === AST_NODE_TYPES.JSXExpressionContainer) {
    return extractStrings(node.expression);
  }
  if (node.type === AST_NODE_TYPES.CallExpression) {
    return node.arguments.flatMap(extractStrings);
  }
  if (node.type === AST_NODE_TYPES.ArrayExpression) {
    return node.elements.flatMap(e => e ? extractStrings(e) : []);
  }
  if (node.type === AST_NODE_TYPES.LogicalExpression) {
    return [...extractStrings(node.left), ...extractStrings(node.right)];
  }
  if (node.type === AST_NODE_TYPES.ConditionalExpression) {
    return [...extractStrings(node.consequent), ...extractStrings(node.alternate)];
  }
  return [];
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "require-interactive-states",
  meta: {
    type: "problem",
    docs: {
      description: "Require hover: and focus-visible: classes on interactive elements to prevent dead UIs.",
    },
    schema: [],
    messages: {
      missingInteractiveStates: "Interactive elements must include both hover: and focus-visible: utility classes.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      JSXOpeningElement(node: TSESTree.JSXOpeningElement): void {
        if (node.name.type !== "JSXIdentifier") {
          return;
        }

        const elementName = node.name.name;

        // Check if it's an interactive element
        if (elementName === "a") {
          const hasHref = node.attributes.some(
            (attr) =>
              attr.type === AST_NODE_TYPES.JSXAttribute &&
              attr.name.type === AST_NODE_TYPES.JSXIdentifier &&
              attr.name.name === "href"
          );
          if (!hasHref) {
            return;
          }
        } else if (!INTERACTIVE_ELEMENTS.has(elementName)) {
          return;
        }

        const classNameAttr = node.attributes.find(
          (attr) =>
            attr.type === AST_NODE_TYPES.JSXAttribute &&
            attr.name.type === AST_NODE_TYPES.JSXIdentifier &&
            attr.name.name === "className"
        );

        let hasHover = false;
        let hasFocusVisible = false;

        if (classNameAttr && classNameAttr.type === AST_NODE_TYPES.JSXAttribute && classNameAttr.value) {
          const strings = extractStrings(classNameAttr.value);
          for (const str of strings) {
            if (str.includes("hover:")) {
              hasHover = true;
            }
            if (str.includes("focus-visible:")) {
              hasFocusVisible = true;
            }
          }
        }

        if (!hasHover || !hasFocusVisible) {
          context.report({
            node,
            messageId: "missingInteractiveStates",
          });
        }
      },
    };
  },
});
