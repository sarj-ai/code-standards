/**
 * @fileoverview no-unlocalized-jsx-attributes — statically proven UI policy violations receive actionable diagnostics.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unlocalized-jsx-attributes.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { attributeText } from "./_jsx-accessibility.js";
import {
  LOCALIZATION_PROPERTIES,
  localizationExcluded,
  type LocalizationOptions,
  needsTranslation,
  withinTranslation,
} from "./_localization.js";

type Options = readonly [
  (LocalizationOptions & { readonly attributes?: readonly string[] })?,
];

export const NO_UNLOCALIZED_JSX_ATTRIBUTES_DOCUMENTATION = {
  summary:
    "Require translation for literal user-visible JSX attributes in opted-in localized interfaces.",
  rationale:
    "Accessible labels and placeholders must follow the interface language along with visible copy.",
  remediation:
    "Pass the user-facing message through the configured translation API, or explicitly exempt text that must remain literal.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Standalone rule activation opts into localization for the selected files. No particular locale or translation function name is required. Generated files, tests, fixtures and stories are excluded.",
    "Default attributes are title, placeholder, alt, aria-label and aria-description. Custom attribute names are configurable. ID-reference attributes are always excluded. Later spreads make values unknown; dynamic expressions are not proven translated.",
  ],
  examples: [
    {
      id: "literal-message",
      title: "Translate a user-facing message",
      outcome: "match",
      files: [
        { path: "src/message.tsx", source: '<input placeholder="Search" />' },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "translated-message",
      title: "Resolve the message through translation",
      outcome: "no-match",
      files: [
        {
          path: "src/message.tsx",
          source: '<input placeholder={t("search")} />',
        },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

const ID_REFERENCES: ReadonlySet<string> = new Set([
  "aria-labelledby",
  "aria-describedby",
  "aria-controls",
  "aria-owns",
  "aria-activedescendant",
  "aria-details",
  "aria-errormessage",
  "aria-flowto",
  "htmlFor",
  "id",
]);

export default createRule<Options, "unlocalized">({
  name: "no-unlocalized-jsx-attributes",
  documentation: NO_UNLOCALIZED_JSX_ATTRIBUTES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_UNLOCALIZED_JSX_ATTRIBUTES_DOCUMENTATION.summary },
    schema: [
      {
        type: "object",
        properties: {
          ...LOCALIZATION_PROPERTIES,
          attributes: {
            type: "array",
            items: { type: "string", minLength: 1 },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      unlocalized:
        "Translate this user-facing literal or add an explicit localization exception.",
    },
  },
  defaultOptions: [{ enabled: true }],
  create(context, [options]) {
    if (
      localizationExcluded(context.filename, context.sourceCode.text, options)
    )
      return {};
    const attributes = options?.attributes ?? [
      "title",
      "placeholder",
      "alt",
      "aria-label",
      "aria-description",
    ];

    return {
      JSXOpeningElement(node): void {
        if (withinTranslation(node.parent, context.sourceCode, options)) return;
        for (const name of attributes) {
          if (ID_REFERENCES.has(name)) continue;
          const text = attributeText(node, name);
          if (text === null || !needsTranslation(text, options)) continue;
          const attribute = node.attributes.findLast(
            (entry) =>
              entry.type === AST_NODE_TYPES.JSXAttribute &&
              entry.name.type === AST_NODE_TYPES.JSXIdentifier &&
              entry.name.name === name,
          );
          if (attribute !== undefined)
            context.report({ node: attribute, messageId: "unlocalized" });
        }
      },
    };
  },
});
