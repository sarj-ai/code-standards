/**
 * @fileoverview prefer-shadcn-primitives — visible application UI should use shared shadcn primitives.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-shadcn-primitives.test.ts
 */

import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isTestFile } from "./_paths.js";

type MessageIds = "preferShadcnPrimitive";
export interface RuleOptions {
  readonly assumeAvailable?: boolean;
}
type Options = readonly [RuleOptions?];

export const preferShadcnPrimitivesDocumentation = {
  summary: "Require visible raw JSX controls to use the corresponding shared shadcn primitive.",
  rationale: "Shared primitives centralize interaction, accessibility, and visual behavior across the product.",
  remediation: "Replace the raw visible control with the corresponding shared shadcn component.",
  category: "style",
  limitations: [
    "Hidden and file inputs, unassociated labels, and non-control semantic elements are excluded.",
    "Tests and the shared components/ui primitive implementation tree are excluded.",
  ],
  examples: [
    { id: "shared-button", title: "Use a shared button", outcome: "no-match", files: [{ path: "src/form.tsx", source: "import { Button } from '@/components/ui/button'; const action = <Button>Save</Button>;" }], focusPath: "src/form.tsx", expectedCount: 0, public: true },
    { id: "raw-button", title: "Do not use a raw button", outcome: "match", files: [{ path: "src/form.tsx", source: "import { Card } from '@/components/ui/card'; const action = <button>Save</button>;" }], focusPath: "src/form.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;

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

const SHARED_PRIMITIVE_IMPLEMENTATION_RE =
  /(?:^|\/)components\/ui(?:\/|$)/i;
const SHARED_PRIMITIVE_IMPORT_RE =
  /(?:^|\/)components\/ui\/[^/]+$/i;
const AMBIGUOUS_INPUT_TYPES: ReadonlySet<string> = new Set([
  "button",
  "color",
  "image",
  "range",
  "reset",
  "submit",
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

function staticString(value: TSESTree.JSXAttribute["value"]): string | null {
  if (value?.type === AST_NODE_TYPES.Literal) {
    return typeof value.value === "string" ? value.value : null;
  }
  if (value?.type !== AST_NODE_TYPES.JSXExpressionContainer) return null;
  return staticExpressionString(value.expression);
}

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
  if (AMBIGUOUS_INPUT_TYPES.has(inputType)) return null;
  return "Input";
}

export default createRule<Options, MessageIds>({
  name: "prefer-shadcn-primitives",
  documentation: preferShadcnPrimitivesDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require visible raw JSX controls to use the corresponding shared shadcn primitive.",
    },
    schema: [
      {
        type: "object",
        properties: {
          assumeAvailable: { type: "boolean" },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      preferShadcnPrimitive:
        "Use the shared {{ replacement }} shadcn primitive instead of raw <{{ element }}> markup.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    const filename = context.filename.replaceAll("\\", "/");
    if (
      isTestFile(filename) ||
      SHARED_PRIMITIVE_IMPLEMENTATION_RE.test(filename)
    ) {
      return {};
    }
    // ESLint rules see one file at a time. Require local proof that the
    // repository actually owns a shadcn primitive tree before prescribing it;
    // otherwise every raw control in a non-shadcn project becomes noise.
    let hasSharedPrimitiveImport = options?.assumeAvailable ?? false;
    const candidates: Array<{
      readonly element: RawPrimitive;
      readonly node: TSESTree.JSXOpeningElement;
      readonly replacement: string;
    }> = [];
    return {
      ImportDeclaration(node): void {
        if (
          typeof node.source.value === "string" &&
          SHARED_PRIMITIVE_IMPORT_RE.test(node.source.value)
        ) {
          hasSharedPrimitiveImport = true;
        }
      },
      JSXOpeningElement(node): void {
        const element = rawElementName(node);
        if (element === null) return;
        if (element === "label" && !isStaticallyAssociatedLabel(node)) return;
        const replacement = replacementFor(node, element);
        if (replacement === null) return;
        candidates.push({ element, node, replacement });
      },
      "Program:exit"(): void {
        if (!hasSharedPrimitiveImport) return;
        for (const { element, node, replacement } of candidates) {
          context.report({
            node,
            messageId: "preferShadcnPrimitive",
            data: { element, replacement },
          });
        }
      },
    };
  },
});
