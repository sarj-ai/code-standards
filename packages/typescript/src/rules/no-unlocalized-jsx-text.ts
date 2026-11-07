/**
 * @fileoverview no-unlocalized-jsx-text — statically proven UI policy violations receive actionable diagnostics.
 *
 * Port of the 18.x `no-unlocalized-jsx-text` rule. The rule is untyped,
 * so the port covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { staticText } from "../utils/jsx-accessibility.js";
import {
  LOCALIZATION_PROPERTIES,
  localizationExcluded,
  type LocalizationOptions,
  needsTranslation,
  withinTranslation,
} from "../utils/localization.js";

const NAME = "no-unlocalized-jsx-text";

export default defineRule({
  meta: {
    defaultOptions: [{ enabled: true }],
    type: "suggestion",
    docs: {
      description: "Require translation for literal JSX text in opted-in localized interfaces.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: { ...LOCALIZATION_PROPERTIES },
        additionalProperties: false,
      },
    ],
    messages: {
      unlocalized: "Translate this user-facing literal or add an explicit localization exception.",
    },
  },
  createOnce(context) {
    let options: LocalizationOptions | undefined;
    return {
      before() {
        options = context.options[0] as LocalizationOptions | undefined;
        if (localizationExcluded({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text, options))
          return false;
        return undefined;
      },
      JSXText(node: ESTree.JSXText): void {
        if (needsTranslation(node.value, options) && !withinTranslation(node, context.sourceCode, options))
          context.report({ node, messageId: "unlocalized" });
      },
      JSXExpressionContainer(node: ESTree.JSXExpressionContainer): void {
        if (node.parent.type !== "JSXElement" && node.parent.type !== "JSXFragment") return;
        const text = staticText(node);
        if (text !== null && needsTranslation(text, options) && !withinTranslation(node, context.sourceCode, options))
          context.report({ node, messageId: "unlocalized" });
      },
    };
  },
});
