import { ESLintUtils, type TSESTree, AST_NODE_TYPES } from "@typescript-eslint/utils";

type MessageIds = "preferShadcn";
type Options = readonly [];

const REPLACEMENTS: Readonly<Record<string, string>> = {
  button: "Button",
  input: "Input",
  select: "Select",
  textarea: "Textarea",
  dialog: "Dialog",
};

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "prefer-shadcn",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Prefer shadcn/ui form primitives over native `<input>`, `<select>`, `<textarea>`, `<button>`, and `<dialog>` elements.",
    },
    schema: [],
    messages: {
      preferShadcn:
        "Use the shadcn <{{replacement}}> component from @/components/ui/{{lowercase}} instead of native <{{element}}>.",
    },
  },
  defaultOptions: [],
  create(context) {
    const filename = context.filename || context.getPhysicalFilename?.() || "";
    
    // Exclude components/ui/* and email paths to prevent false positives and infinite recursion.
    if (
      filename.includes("components/ui/") ||
      filename.includes("components\\ui\\") ||
      filename.includes("email") ||
      filename.includes("emails")
    ) {
      return {};
    }

    return {
      JSXOpeningElement(node: TSESTree.JSXOpeningElement): void {
        // Only lowercase JSXIdentifier names represent native HTML elements.
        if (node.name.type !== "JSXIdentifier") {
          return;
        }

        const elementName = node.name.name;
        const replacement = REPLACEMENTS[elementName];

        if (replacement === undefined) {
          return;
        }

        // Special handling for <input>
        if (elementName === "input") {
          const typeAttribute = node.attributes.find(
            (attr) =>
              attr.type === AST_NODE_TYPES.JSXAttribute &&
              attr.name.type === AST_NODE_TYPES.JSXIdentifier &&
              attr.name.name === "type"
          );

          if (typeAttribute && typeAttribute.type === AST_NODE_TYPES.JSXAttribute) {
            const value = typeAttribute.value;
            if (value?.type === AST_NODE_TYPES.Literal && value.value === "hidden") {
              // Ignore <input type="hidden">
              return;
            }
          }
        }

        context.report({
          node,
          messageId: "preferShadcn",
          data: {
            element: elementName,
            replacement,
            lowercase: replacement.toLowerCase(),
          },
        });
      },
    };
  },
});
