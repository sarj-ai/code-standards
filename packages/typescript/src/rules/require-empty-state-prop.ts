import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

type MessageIds = "requireEmptyState";
type Options = readonly [];

const TARGET_COMPONENTS = new Set(["Table", "List", "DataGrid", "Feed"]);

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "require-empty-state-prop",
  meta: {
    type: "problem",
    docs: {
      description:
        "Data display components (Table, List, DataGrid, Feed) MUST have an emptyState or renderEmpty prop defined.",
    },
    schema: [],
    messages: {
      requireEmptyState:
        "Data display component <{{component}}> MUST have an `emptyState` or `renderEmpty` prop defined.",
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

        if (!TARGET_COMPONENTS.has(elementName)) {
          return;
        }

        const hasEmptyStateProp = node.attributes.some(
          (attr) =>
            attr.type === AST_NODE_TYPES.JSXAttribute &&
            attr.name.type === AST_NODE_TYPES.JSXIdentifier &&
            (attr.name.name === "emptyState" || attr.name.name === "renderEmpty")
        );

        const hasSpread = node.attributes.some((attr) => attr.type === AST_NODE_TYPES.JSXSpreadAttribute);

        if (!hasEmptyStateProp && !hasSpread) {
          context.report({
            node,
            messageId: "requireEmptyState",
            data: {
              component: elementName,
            },
          });
        }
      },
    };
  },
});
