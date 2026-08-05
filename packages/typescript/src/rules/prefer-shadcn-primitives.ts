/**
 * @fileoverview prefer-shadcn-primitives — visible application UI should use shared shadcn primitives.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-shadcn-primitives.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule } from "./_docs.js";

type MessageIds = "preferShadcnPrimitive";
type Options = readonly [];

const SHADCN_PRIMITIVES = {
  button: "Button",
  dialog: "Dialog or AlertDialog family",
  input: "Input",
  label: "Label",
  progress: "Progress",
  select: "Select family",
  table: "Table family",
  textarea: "Textarea",
} as const;

type RawPrimitive = keyof typeof SHADCN_PRIMITIVES;

const LABELABLE_ELEMENTS: ReadonlySet<string> = new Set([
  "button",
  "input",
  "meter",
  "output",
  "progress",
  "select",
  "textarea",
]);

function rawElementName(
  node: TSESTree.JSXOpeningElement,
): RawPrimitive | null {
  if (node.name.type !== AST_NODE_TYPES.JSXIdentifier) return null;
  const name = node.name.name;
  return Object.hasOwn(SHADCN_PRIMITIVES, name)
    ? (name as RawPrimitive)
    : null;
}

type StaticAttribute =
  | { readonly kind: "known"; readonly value: string }
  | { readonly kind: "missing" }
  | { readonly kind: "unknown" };

function staticExpressionString(
  expression: TSESTree.Expression | TSESTree.JSXEmptyExpression,
): string | null {
  if (expression.type === AST_NODE_TYPES.Literal) {
    return typeof expression.value === "string" ? expression.value : null;
  }
  if (expression.type === AST_NODE_TYPES.TemplateLiteral) {
    let value = expression.quasis[0]?.value.cooked ?? "";
    for (const [index, substitution] of expression.expressions.entries()) {
      const staticSubstitution = staticExpressionString(substitution);
      if (staticSubstitution === null) return null;
      value += staticSubstitution;
      value += expression.quasis[index + 1]?.value.cooked ?? "";
    }
    return value;
  }
  if (
    expression.type === AST_NODE_TYPES.TSAsExpression ||
    expression.type === AST_NODE_TYPES.TSNonNullExpression ||
    expression.type === AST_NODE_TYPES.TSSatisfiesExpression ||
    expression.type === AST_NODE_TYPES.TSTypeAssertion
  ) {
    return staticExpressionString(expression.expression);
  }
  return null;
}

function staticString(value: TSESTree.JSXAttribute["value"]): string | null {
  if (value?.type === AST_NODE_TYPES.Literal) {
    return typeof value.value === "string" ? value.value : null;
  }
  if (value?.type !== AST_NODE_TYPES.JSXExpressionContainer) return null;
  return staticExpressionString(value.expression);
}

function effectiveAttribute(
  node: TSESTree.JSXOpeningElement,
  attributeName: string,
): StaticAttribute {
  for (const attribute of node.attributes.toReversed()) {
    if (attribute.type === AST_NODE_TYPES.JSXSpreadAttribute) {
      return { kind: "unknown" };
    }
    if (
      attribute.name.type !== AST_NODE_TYPES.JSXIdentifier ||
      attribute.name.name !== attributeName
    ) {
      continue;
    }
    const value = staticString(attribute.value);
    return value === null
      ? { kind: "unknown" }
      : { kind: "known", value };
  }
  return { kind: "missing" };
}

function isLabelableElement(node: TSESTree.JSXElement): boolean {
  if (node.openingElement.name.type !== AST_NODE_TYPES.JSXIdentifier) {
    return false;
  }
  const name = node.openingElement.name.name;
  if (!LABELABLE_ELEMENTS.has(name)) return false;
  if (name !== "input") return true;
  const typeAttribute = effectiveAttribute(node.openingElement, "type");
  if (typeAttribute.kind === "unknown") return false;
  return !(
    typeAttribute.kind === "known" &&
    typeAttribute.value.toLowerCase() === "hidden"
  );
}

function containsLabelableElement(
  node: TSESTree.JSXElement | TSESTree.JSXFragment,
): boolean {
  return node.children.some((child) => {
    if (child.type === AST_NODE_TYPES.JSXElement) {
      return isLabelableElement(child) || containsLabelableElement(child);
    }
    if (child.type === AST_NODE_TYPES.JSXFragment) {
      return containsLabelableElement(child);
    }
    return false;
  });
}

function isStaticallyAssociatedLabel(node: TSESTree.JSXOpeningElement): boolean {
  const htmlFor = effectiveAttribute(node, "htmlFor");
  if (htmlFor.kind === "known" && htmlFor.value.trim().length > 0) return true;
  return (
    node.parent.type === AST_NODE_TYPES.JSXElement &&
    containsLabelableElement(node.parent)
  );
}

function replacementFor(
  node: TSESTree.JSXOpeningElement,
  element: RawPrimitive,
): string | null {
  if (element !== "input") return SHADCN_PRIMITIVES[element];
  const typeAttribute = effectiveAttribute(node, "type");
  if (typeAttribute.kind === "unknown") return null;
  const inputType =
    typeAttribute.kind === "known" ? typeAttribute.value.toLowerCase() : "text";
  if (inputType === "hidden" || inputType === "file") return null;
  if (inputType === "checkbox") return "Checkbox";
  if (inputType === "radio") return "RadioGroup family";
  return "Input";
}

export default createRule<Options, MessageIds>({
  name: "prefer-shadcn-primitives",
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require visible raw JSX controls to use the corresponding shared shadcn primitive.",
    },
    schema: [],
    messages: {
      preferShadcnPrimitive:
        "Use the shared {{ replacement }} shadcn primitive instead of raw <{{ element }}> markup.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      JSXOpeningElement(node): void {
        const element = rawElementName(node);
        if (element === null) return;
        if (element === "label" && !isStaticallyAssociatedLabel(node)) return;
        const replacement = replacementFor(node, element);
        if (replacement === null) return;
        context.report({
          node,
          messageId: "preferShadcnPrimitive",
          data: { element, replacement },
        });
      },
    };
  },
});
