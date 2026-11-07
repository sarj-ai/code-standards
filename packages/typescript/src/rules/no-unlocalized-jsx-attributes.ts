/**
 * @fileoverview no-unlocalized-jsx-attributes — statically proven UI policy violations receive actionable diagnostics.
 *
 * Port of the 18.x `no-unlocalized-jsx-attributes` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule, type ESTree } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { attributeText } from "../utils/jsx-accessibility.js";
import {
  LOCALIZATION_PROPERTIES,
  localizationExcluded,
  type LocalizationOptions,
  needsTranslation,
  withinTranslation,
} from "../utils/localization.js";

const NAME = "no-unlocalized-jsx-attributes";

type Options = LocalizationOptions & { readonly attributes?: readonly string[] };

const DEFAULT_ATTRIBUTES: readonly string[] = ["title", "placeholder", "alt", "aria-label", "aria-description"];

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

export default defineRule({
  meta: {
    defaultOptions: [{ enabled: true }],
    type: "suggestion",
    docs: {
      description: "Require translation for literal user-visible JSX attributes in opted-in localized interfaces.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          ...LOCALIZATION_PROPERTIES,
          attributes: {
            description: "JSX attributes whose user-visible text requires localization.",
            type: "array",
            items: { type: "string", minLength: 1 },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      unlocalized: "Translate this user-facing literal or add an explicit localization exception.",
    },
  },
  createOnce(context) {
    let options: Options | undefined;
    let attributes: readonly string[] = DEFAULT_ATTRIBUTES;
    return {
      before() {
        options = context.options[0] as Options | undefined;
        if (localizationExcluded({ filename: context.filename, cwd: context.cwd }, context.sourceCode.text, options))
          return false;
        attributes = (options?.attributes ?? DEFAULT_ATTRIBUTES).filter((name) => !ID_REFERENCES.has(name));
        return undefined;
      },
      JSXOpeningElement(node: ESTree.JSXOpeningElement): void {
        const unlocalized = attributes.flatMap((name) => {
          const text = attributeText(node, name);
          if (text === null || !needsTranslation(text, options)) return [];
          const attribute = node.attributes.findLast(
            (entry) =>
              entry.type === "JSXAttribute" &&
              entry.name.type === "JSXIdentifier" &&
              entry.name.name === name,
          );
          return attribute === undefined ? [] : [attribute];
        });
        // The ancestor walk runs only for an element that has a literal to report.
        if (unlocalized.length === 0 || withinTranslation(node.parent, context.sourceCode, options)) return;
        for (const attribute of unlocalized) context.report({ node: attribute, messageId: "unlocalized" });
      },
    };
  },
});
