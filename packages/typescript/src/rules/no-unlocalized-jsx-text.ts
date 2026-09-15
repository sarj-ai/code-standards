/**
 * @fileoverview no-unlocalized-jsx-text — statically proven UI policy violations receive actionable diagnostics.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-unlocalized-jsx-text.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { staticText } from "./_jsx-accessibility.js";
import {
  LOCALIZATION_PROPERTIES,
  localizationExcluded,
  type LocalizationOptions,
  needsTranslation,
  withinTranslation,
} from "./_localization.js";

type Options = readonly [LocalizationOptions?];

export const NO_UNLOCALIZED_JSX_TEXT_DOCUMENTATION = {
  summary:
    "Require translation for literal JSX text in opted-in localized interfaces.",
  rationale: "Literal UI copy cannot change with the selected language.",
  remediation:
    "Pass the user-facing message through the configured translation API, or explicitly exempt text that must remain literal.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Standalone rule activation opts into localization for the selected files. No particular locale or translation function name is required. Generated files, tests, fixtures and stories are excluded.",
    'Only direct JSX text and complete literal expression children containing Unicode letters are checked. Dynamic expressions are not proven translated. Text inside code and samp elements is treated as technical content; their user-facing attributes are still checked by the attribute rule. translate="no" and configured translation component imports are respected; nested translate="yes" re-enables checking.',
  ],
  examples: [
    {
      id: "literal-message",
      title: "Translate a user-facing message",
      outcome: "match",
      files: [{ path: "src/message.tsx", source: "<p>Hello</p>" }],
      focusPath: "src/message.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "translated-message",
      title: "Resolve the message through translation",
      outcome: "no-match",
      files: [{ path: "src/message.tsx", source: '<p>{t("hello")}</p>' }],
      focusPath: "src/message.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, "unlocalized">({
  name: "no-unlocalized-jsx-text",
  documentation: NO_UNLOCALIZED_JSX_TEXT_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: { description: NO_UNLOCALIZED_JSX_TEXT_DOCUMENTATION.summary },
    schema: [
      {
        type: "object",
        properties: { ...LOCALIZATION_PROPERTIES },
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
    return {
      JSXText(node): void {
        if (
          needsTranslation(node.value, options) &&
          !withinTranslation(node, context.sourceCode, options)
        )
          context.report({ node, messageId: "unlocalized" });
      },
      JSXExpressionContainer(node): void {
        if (
          node.parent.type !== AST_NODE_TYPES.JSXElement &&
          node.parent.type !== AST_NODE_TYPES.JSXFragment
        )
          return;
        const text = staticText(node);
        if (
          text !== null &&
          needsTranslation(text, options) &&
          !withinTranslation(node, context.sourceCode, options)
        )
          context.report({ node, messageId: "unlocalized" });
      },
    };
  },
});
