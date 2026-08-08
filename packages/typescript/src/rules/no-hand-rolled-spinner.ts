/**
 * @fileoverview no-hand-rolled-spinner — border-ring loading indicators should use the design-system spinner.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-hand-rolled-spinner.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "handRolledSpinner";
type Options = readonly [];

export const noHandRolledSpinnerDocumentation = {
  summary: "Disallow intrinsic elements styled as Tailwind border-ring spinners outside the design-system implementation.",
  rationale: "One-off loading indicators duplicate a shared primitive and let accessibility and styling diverge.",
  remediation: "Render the design-system Spinner component instead.",
  category: "maintainability",
  limitations: ["Only static className values on div and span elements are inspected."],
  examples: [
    { id: "design-system-spinner", title: "Use the shared spinner", outcome: "no-match", files: [{ path: "src/loading-state.tsx", source: '<Spinner className="size-4" />' }], focusPath: "src/loading-state.tsx", expectedCount: 0, public: true },
    { id: "border-ring-spinner", title: "Do not rebuild a spinner", outcome: "match", files: [{ path: "src/loading-state.tsx", source: '<div className="size-4 animate-spin rounded-full border-2 border-t-transparent" />' }], focusPath: "src/loading-state.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const DESIGN_SYSTEM_PATH = /(?:^|[/\\])components[/\\]ui[/\\]/u;
const BORDER_WIDTH = /^border(?:-[0-9]+)?$/u;
const TRANSPARENT_EDGE = /^border-[trbl]-transparent$/u;

function staticClassName(attribute: TSESTree.JSXAttribute): string | null {
  const value = attribute.value;
  if (value?.type === AST_NODE_TYPES.Literal && typeof value.value === "string") {
    return value.value;
  }
  if (
    value?.type === AST_NODE_TYPES.JSXExpressionContainer &&
    value.expression.type === AST_NODE_TYPES.Literal &&
    typeof value.expression.value === "string"
  ) {
    return value.expression.value;
  }
  return null;
}

export default createRule<Options, MessageIds>({
  name: "no-hand-rolled-spinner",
  documentation: noHandRolledSpinnerDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow intrinsic elements styled as Tailwind border-ring spinners outside the design-system implementation.",
    },
    schema: [],
    messages: {
      handRolledSpinner:
        "Use the design-system Spinner component instead of rebuilding a border-ring spinner with utility classes.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (DESIGN_SYSTEM_PATH.test(context.filename)) {
      return {};
    }

    return {
      JSXOpeningElement(node): void {
        if (
          node.name.type !== AST_NODE_TYPES.JSXIdentifier ||
          (node.name.name !== "div" && node.name.name !== "span")
        ) {
          return;
        }
        const classNameAttribute = node.attributes.find(
          (attribute): attribute is TSESTree.JSXAttribute =>
            attribute.type === AST_NODE_TYPES.JSXAttribute &&
            attribute.name.type === AST_NODE_TYPES.JSXIdentifier &&
            attribute.name.name === "className",
        );
        if (classNameAttribute === undefined) return;
        const className = staticClassName(classNameAttribute);
        if (className === null) return;
        const classes = className.split(/\s+/u);
        if (
          classes.includes("animate-spin") &&
          classes.includes("rounded-full") &&
          classes.some((token) => BORDER_WIDTH.test(token)) &&
          classes.some((token) => TRANSPARENT_EDGE.test(token))
        ) {
          context.report({ node, messageId: "handRolledSpinner" });
        }
      },
    };
  },
});
