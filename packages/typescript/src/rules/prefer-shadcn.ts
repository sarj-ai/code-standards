/**
 * @fileoverview Prefer shadcn/ui form primitives over their native HTML
 * counterparts. Limited to form/dialog elements — `<button>` and `<table>`
 * have been removed from the forbid list because they produced 100% false
 * positives during bulbul validation (icon buttons, layout tables).
 *
 * `<input>` is resolved by its `type`: a bare `<input type="checkbox">` maps to
 * `<Checkbox>`, `radio` → `<RadioGroup>`, `range` → `<Slider>`, and the text-like
 * types (or no type) → `<Input>`. `type="hidden"` and native file upload controls
 * are skipped (no shadcn primitive), and a dynamic `type={…}` falls back to the
 * generic `<Input>` rather than asserting a wrong primitive.
 *
 * TEST FILES ARE EXEMPT. Corpus sweep (2220 files across zod / TanStack Query /
 * react-router / swr / zustand, 2026-07): 84 raw hits, 53 of them in a single
 * react-router suite. JSX inside a test is not a user interface — it is the
 * smallest possible DOM that makes an assertion reachable.
 * `react-router/packages/react-router/__tests__/dom/data-browser-router-test.tsx:1415`
 * (`<input name="test" value="value" />` inside a `<Form method="post">`, so the
 * test can assert what the router submitted) is representative: swapping in
 * `<Input>` would add a dependency, change nothing observable, and make the
 * fixture harder to read. The remaining hits, in real screens under
 * `examples/`, still fire.
 */

import {
  AST_NODE_TYPES,
  ESLintUtils,
  type TSESTree,
} from "@typescript-eslint/utils";

import { isStoryFile, isTestFile } from "./_paths.js";

type MessageIds = "preferShadcn";
type Options = readonly [];

const REPLACEMENTS: Readonly<Record<string, string>> = {
  select: "Select",
  textarea: "Textarea",
  dialog: "Dialog",
};

/** `<input type>` → shadcn primitive. Absent types (and text-likes) fall to Input. */
const INPUT_TYPE_REPLACEMENTS: Readonly<Record<string, string>> = {
  checkbox: "Checkbox",
  radio: "RadioGroup",
  range: "Slider",
};

/** `<input type>` values with no shadcn equivalent — never reported. */
const SKIPPED_INPUT_TYPES = new Set<string>(["file", "hidden"]);

const kebabCase = (component: string): string =>
  component.replace(/([a-z0-9])([A-Z])/g, "$1-$2").toLowerCase();

const literalTypeAttr = (
  node: TSESTree.JSXOpeningElement,
): { readonly kind: "literal"; readonly value: string } | { readonly kind: "dynamic" } | null => {
  for (const attribute of node.attributes) {
    if (
      attribute.type !== AST_NODE_TYPES.JSXAttribute ||
      attribute.name.type !== AST_NODE_TYPES.JSXIdentifier ||
      attribute.name.name !== "type"
    ) {
      continue;
    }
    if (attribute.value?.type === AST_NODE_TYPES.Literal && typeof attribute.value.value === "string") {
      return { kind: "literal", value: attribute.value.value.toLowerCase() };
    }
    return { kind: "dynamic" };
  }
  return null;
};

const hasFileAcceptAttr = (node: TSESTree.JSXOpeningElement): boolean =>
  node.attributes.some(
    (attribute) =>
      attribute.type === AST_NODE_TYPES.JSXAttribute &&
      attribute.name.type === AST_NODE_TYPES.JSXIdentifier &&
      attribute.name.name === "accept",
  );

/** Resolve an `<input>` to its shadcn primitive, or null to skip it entirely. */
const resolveInputReplacement = (node: TSESTree.JSXOpeningElement): string | null => {
  const typeAttr = literalTypeAttr(node);
  if (hasFileAcceptAttr(node)) return null;
  if (typeAttr === null || typeAttr.kind === "dynamic") return "Input";
  if (SKIPPED_INPUT_TYPES.has(typeAttr.value)) return null;
  return INPUT_TYPE_REPLACEMENTS[typeAttr.value] ?? "Input";
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
        "Prefer shadcn/ui form primitives over native `<input>`, `<select>`, `<textarea>`, and `<dialog>` elements.",
    },
    schema: [],
    messages: {
      preferShadcn:
        "Use the shadcn <{{replacement}}> component from @/components/ui/{{lowercase}} instead of native <{{element}}>.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isTestFile(context.filename) || isStoryFile(context.filename)) {
      return {};
    }

    return {
      JSXOpeningElement(node: TSESTree.JSXOpeningElement): void {
        // Only lowercase JSXIdentifier names represent native HTML elements.
        // Member expressions (`Foo.Bar`) and namespaces (`svg:path`) are skipped.
        if (node.name.type !== "JSXIdentifier") {
          return;
        }

        const elementName = node.name.name;
        const replacement =
          elementName === "input" ? resolveInputReplacement(node) : REPLACEMENTS[elementName];

        if (replacement === undefined || replacement === null) {
          return;
        }

        context.report({
          node,
          messageId: "preferShadcn",
          data: {
            element: elementName,
            replacement,
            lowercase: kebabCase(replacement),
          },
        });
      },
    };
  },
});
