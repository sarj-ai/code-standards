/**
 * @fileoverview no-hand-rolled-spinner — keep loading spinners in the design system.
 *
 * Port of the 18.x `no-hand-rolled-spinner` rule. The rule is untyped, so
 * the port covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { tailwindBase, tailwindVariantPrefix } from "../utils/tailwind.js";

const NAME = "no-hand-rolled-spinner";

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

interface TailwindClass {
  readonly base: string;
  readonly variant: string;
}

function hasSpinnerInVariant(classes: readonly TailwindClass[], variant: string): boolean {
  const effective = classes
    .filter((entry) => entry.variant === "" || entry.variant === variant)
    .map((entry) => entry.base);
  return effective.includes("animate-spin") &&
    effective.includes("rounded-full") &&
    effective.some(isBorderWidth) &&
    effective.some(isContrastingEdge);
}

function staticClassName(attribute: ESTree.JSXAttribute): string | null {
  const value = attribute.value;
  if (value?.type === "Literal" && typeof value.value === "string") {
    return value.value;
  }
  if (
    value?.type === "JSXExpressionContainer" &&
    value.expression.type === "Literal" &&
    typeof value.expression.value === "string"
  ) {
    return value.expression.value;
  }
  if (
    value?.type === "JSXExpressionContainer" &&
    value.expression.type === "TemplateLiteral" &&
    value.expression.expressions.length === 0
  ) {
    return value.expression.quasis[0]?.value.cooked ?? null;
  }
  return null;
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow intrinsic elements styled as Tailwind border-ring spinners outside the design-system implementation.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      handRolledSpinner:
        "Use the design-system Spinner component instead of rebuilding a border-ring spinner with utility classes.",
    },
  },
  createOnce(context) {
    return {
      before() {
        const file = { filename: context.filename, cwd: context.cwd };
        if (
          DESIGN_SYSTEM_PATH.test(context.filename) ||
          isTestFile(file) ||
          isStoryFile(file) ||
          isGeneratedFile(file, context.sourceCode.text)
        ) return false;
        return undefined;
      },
      JSXOpeningElement(node) {
        if (node.name.type !== "JSXIdentifier" || (node.name.name !== "div" && node.name.name !== "span")) return;
        const classNameAttribute = node.attributes.findLast(
          (attribute) =>
            attribute.type === "JSXSpreadAttribute" ||
            (attribute.type === "JSXAttribute" &&
            attribute.name.type === "JSXIdentifier" &&
            attribute.name.name === "className"),
        );
        if (classNameAttribute?.type !== "JSXAttribute") return;
        const className = staticClassName(classNameAttribute);
        if (className === null) return;
        const classes = className.split(/\s+/u).filter(Boolean).map((token) => ({
          base: tailwindBase(token),
          variant: tailwindVariantPrefix(token),
        }));
        const variants = new Set(classes.map((entry) => entry.variant));
        if ([...variants].some((variant) => hasSpinnerInVariant(classes, variant))) {
          context.report({ node, messageId: "handRolledSpinner" });
        }
      },
    };
  },
});
