/**
 * @fileoverview Require every JSX `<button>` to declare its `type`.
 *
 * Mined from bulbul PR #3483: an auxiliary "browse templates" button inside a
 * form submitted the parent form until the PR added `type="button"`. Native
 * buttons default to `submit`, so omitting the attribute is a latent behavior
 * change whenever markup is moved into a form.
 */

import { AST_NODE_TYPES, ESLintUtils, type TSESTree } from "@typescript-eslint/utils";

import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "missingType";
type Options = readonly [];

function isButtonElementName(name: TSESTree.JSXTagNameExpression): boolean {
  return name.type === AST_NODE_TYPES.JSXIdentifier && name.name === "button";
}

function hasExplicitTypeAttribute(node: TSESTree.JSXOpeningElement): boolean {
  return node.attributes.some(
    (attr) =>
      attr.type === AST_NODE_TYPES.JSXAttribute &&
      attr.name.type === AST_NODE_TYPES.JSXIdentifier &&
      attr.name.name === "type",
  );
}

export default ESLintUtils.RuleCreator(
  (name) =>
    `https://github.com/sarj-ai/linting/blob/main/packages/typescript/src/rules/${name}.ts`,
)<Options, MessageIds>({
  name: "button-requires-type",
  meta: {
    type: "problem",
    docs: {
      description:
        "Require JSX `<button>` elements to declare `type`, avoiding accidental form submissions.",
    },
    schema: [],
    messages: {
      missingType:
        "Declare this button's `type` explicitly (`button`, `submit`, or `reset`). Native buttons default to `submit`, which causes accidental form submission when markup moves inside a form.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (
      isTestFile(context.filename) ||
      isStoryFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.getText())
    ) {
      return {};
    }

    return {
      JSXOpeningElement(node) {
        if (!isButtonElementName(node.name) || hasExplicitTypeAttribute(node)) {
          return;
        }
        context.report({ node: node.name, messageId: "missingType" });
      },
    };
  },
});
