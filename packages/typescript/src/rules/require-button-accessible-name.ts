/**
 * @fileoverview require-button-accessible-name — statically proven UI policy violations receive actionable diagnostics.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/require-button-accessible-name.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import {
  attributeNameStatus,
  childrenNameStatus,
  COMPONENT_IMPORT_SCHEMA,
  type ComponentImport,
  importedComponent,
  isHidden,
  isPassedAsProp,
  hasHiddenAncestor,
} from "./_jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";

type Options = readonly [
  {
    readonly components?: readonly ComponentImport[];
    readonly iconModules?: readonly string[];
  }?,
];

export const REQUIRE_BUTTON_ACCESSIBLE_NAME_DOCUMENTATION = {
  summary:
    "Require an accessible name on statically unnamed native or configured JSX buttons.",
  rationale:
    "An icon-only action without an accessible name cannot communicate its purpose to assistive technology.",
  remediation:
    "Provide meaningful visible or visually hidden text, aria-label, or aria-labelledby for the action.",
  category: "correctness",
  limitations: [
    "Native button and conventional Button elements are checked by default. Other custom buttons require exact module/export configuration; aliases and namespace imports are resolved by scope. Lucide icons are recognized by default; other icon modules are configurable.",
    "Composed JSX passed as props, render/asChild adapters, dynamic labels, children, unknown components, and prop spreads are left to runtime accessibility testing. Referenced IDs, CSS visibility, and meaningful wording are not verified. Generated files, tests, fixtures, and stories are excluded. No automatic labels are invented.",
  ],
  examples: [
    {
      id: "unnamed-button",
      title: "Name an icon action",
      outcome: "match",
      files: [
        {
          path: "src/action.tsx",
          source: '<button><svg aria-hidden="true" /></button>',
        },
      ],
      focusPath: "src/action.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "named-button",
      title: "Provide the action name",
      outcome: "no-match",
      files: [
        {
          path: "src/action.tsx",
          source:
            '<button aria-label="Close"><svg aria-hidden="true" /></button>',
        },
      ],
      focusPath: "src/action.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, "missingName">({
  name: "require-button-accessible-name",
  documentation: REQUIRE_BUTTON_ACCESSIBLE_NAME_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: REQUIRE_BUTTON_ACCESSIBLE_NAME_DOCUMENTATION.summary },
    schema: [
      {
        type: "object",
        properties: {
          components: COMPONENT_IMPORT_SCHEMA,
          iconModules: {
            type: "array",
            items: { type: "string", minLength: 1 },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      missingName:
        "This button has no statically identifiable accessible name. Add action text, aria-label, or aria-labelledby.",
    },
  },
  defaultOptions: [{}],
  create(context, [options]) {
    if (
      isGeneratedFile(context.filename, context.sourceCode.text) ||
      isTestFile(context.filename) ||
      isStoryFile(context.filename)
    )
      return {};
    const iconModules = options?.iconModules ?? ["lucide-react"];
    return {
      JSXElement(node): void {
        const opening = node.openingElement;
        const native =
          opening.name.type === AST_NODE_TYPES.JSXIdentifier &&
          opening.name.name === "button";
        const conventional =
          opening.name.type === AST_NODE_TYPES.JSXIdentifier &&
          opening.name.name === "Button";
        const imported =
          native || conventional
            ? null
            : importedComponent(opening.name, context.sourceCode);
        if (
          !native &&
          !conventional &&
          !options?.components?.some(
            (component) =>
              component.module === imported?.module &&
              component.export === imported.export,
          )
        )
          return;
        if (
          !native &&
          opening.attributes.some(
            (attribute) =>
              attribute.type === AST_NODE_TYPES.JSXAttribute &&
              attribute.name.type === AST_NODE_TYPES.JSXIdentifier &&
              ["render", "asChild"].includes(attribute.name.name),
          )
        )
          return;
        if (
          isPassedAsProp(node, context.sourceCode) ||
          hasHiddenAncestor(node, context.sourceCode)
        )
          return;
        if (isHidden(opening) || attributeNameStatus(opening) !== "empty")
          return;
        if (
          childrenNameStatus(node.children, context.sourceCode, iconModules) !==
          "empty"
        )
          return;
        context.report({ node: opening, messageId: "missingName" });
      },
    };
  },
});
