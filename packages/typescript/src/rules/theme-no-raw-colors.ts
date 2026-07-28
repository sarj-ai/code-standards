import { ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

type MessageIds = "noRawHexColor";
type Options = readonly [];

const HEX_COLOR_REGEX = /(^|[^a-zA-Z0-9])#([0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})(?=[^a-zA-Z0-9]|$)/;

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "theme-no-raw-colors",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow raw hex colors and arbitrary Tailwind bracket colors in favor of design system tokens.",
    },
    schema: [],
    messages: {
      noRawHexColor:
        "Avoid using raw hex colors (e.g., #FF0000) or arbitrary Tailwind bracket colors. Use design system tokens (e.g., `bg-primary` or OKLCH variables) instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    function checkString(node: TSESTree.Node, value: string) {
      if (HEX_COLOR_REGEX.test(value)) {
        context.report({
          node,
          messageId: "noRawHexColor",
        });
      }
    }

    return {
      Literal(node: TSESTree.Literal): void {
        if (typeof node.value === "string") {
          checkString(node, node.value);
        }
      },
      TemplateElement(node: TSESTree.TemplateElement): void {
        checkString(node, node.value.raw);
      },
      JSXText(node: TSESTree.JSXText): void {
        checkString(node, node.value);
      },
    };
  },
});
