/**
 * @fileoverview no-hand-rolled-spinner — border-ring loading indicators should use the design-system spinner.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-hand-rolled-spinner.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "handRolledSpinner";
type Options = readonly [];

export const noHandRolledSpinnerDocumentation = {
  summary: "Disallow intrinsic elements styled as Tailwind border-ring spinners outside the design-system implementation.",
  rationale: "One-off loading indicators duplicate a shared primitive and let accessibility and styling diverge.",
  remediation: "Render the design-system Spinner component instead.",
  category: "maintainability",
  limitations: ["Only static className values on div and span elements are inspected; tests, stories, generated files, and the design-system implementation are excluded."],
  examples: [
    { id: "design-system-spinner", title: "Use the shared spinner", outcome: "no-match", files: [{ path: "src/loading-state.tsx", source: '<Spinner className="size-4" />' }], focusPath: "src/loading-state.tsx", expectedCount: 0, public: true },
    { id: "border-ring-spinner", title: "Do not rebuild a spinner", outcome: "match", files: [{ path: "src/loading-state.tsx", source: '<div className="size-4 animate-spin rounded-full border-2 border-t-transparent" />' }], focusPath: "src/loading-state.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

const DESIGN_SYSTEM_PATH = /(?:^|[/\\])components[/\\]ui[/\\]/u;
const DIRECTIONAL_BORDER = /^border-([trblsexy])-(.+)$/u;
const CSS_LENGTH =
  /^-?(?:\d+(?:\.\d+)?|\.\d+)(?:cap|ch|cm|dvh|dvw|em|ex|ic|in|lh|lvh|lvw|mm|pc|pt|px|q|rcap|rch|rem|rex|ric|rlh|svh|svw|vb|vh|vi|vmax|vmin|vw|%)$/u;
const ARBITRARY_LENGTH_FUNCTION = /^(?:calc|clamp|max|min)\(.+\)$/u;

function isBorderWidthValue(value: string): boolean {
  if (/^\d+$/u.test(value)) return true;
  if (value.startsWith("[") && value.endsWith("]")) {
    const arbitrary = value.slice(1, -1);
    const length = arbitrary.startsWith("length:")
      ? arbitrary.slice("length:".length)
      : arbitrary;
    return (
      CSS_LENGTH.test(length) ||
      ARBITRARY_LENGTH_FUNCTION.test(length) ||
      (arbitrary.startsWith("length:") && /^var\(.+\)$/u.test(length))
    );
  }
  return (
    value.startsWith("(length:") &&
    value.endsWith(")") &&
    value.length > "(length:)".length
  );
}

function isBorderWidth(token: string): boolean {
  return token === "border" ||
    (token.startsWith("border-") &&
      isBorderWidthValue(token.slice("border-".length)));
}

function isContrastingEdge(token: string): boolean {
  const match = DIRECTIONAL_BORDER.exec(token);
  return match?.[2] !== undefined && !isBorderWidthValue(match[2]);
}

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
  if (
    value?.type === AST_NODE_TYPES.JSXExpressionContainer &&
    value.expression.type === AST_NODE_TYPES.TemplateLiteral &&
    value.expression.expressions.length === 0
  ) {
    return value.expression.quasis[0]?.value.cooked ?? null;
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
    if (
      DESIGN_SYSTEM_PATH.test(context.filename) ||
      isTestFile(context.filename) ||
      isStoryFile(context.filename) ||
      isGeneratedFile(context.filename, context.sourceCode.text)
    ) {
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
          classes.some(isBorderWidth) &&
          classes.some(isContrastingEdge)
        ) {
          context.report({ node, messageId: "handRolledSpinner" });
        }
      },
    };
  },
});
