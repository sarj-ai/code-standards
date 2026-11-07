/**
 * @fileoverview prefer-logical-tailwind-utilities — statically proven UI policy violations receive actionable diagnostics.
 *
 * Port of the 18.x `prefer-logical-tailwind-utilities` rule. The rule is
 * untyped, so the port covers all of it.
 */

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { attributeText } from "../utils/jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "../utils/paths.js";
import { classTokens, tailwindVariantPrefix } from "../utils/tailwind.js";

interface Options {
  readonly enabled?: boolean;
  readonly checkInsets?: boolean;
  readonly allowUtilities?: readonly string[];
}

const NAME = "prefer-logical-tailwind-utilities";

const PREFIXES: Readonly<Record<string, string>> = {
  ml: "ms",
  mr: "me",
  pl: "ps",
  pr: "pe",
  "border-l": "border-s",
  "border-r": "border-e",
  "rounded-l": "rounded-s",
  "rounded-r": "rounded-e",
  "rounded-tl": "rounded-ss",
  "rounded-tr": "rounded-se",
  "rounded-bl": "rounded-es",
  "rounded-br": "rounded-ee",
};
const EXACT: Readonly<Record<string, string>> = {
  "text-left": "text-start",
  "text-right": "text-end",
  "float-left": "float-start",
  "float-right": "float-end",
  "clear-left": "clear-start",
  "clear-right": "clear-end",
};

const PREFIX_ENTRIES: readonly (readonly [string, string])[] = Object.entries(PREFIXES);
const INSET_PREFIX_ENTRIES: readonly (readonly [string, string])[] = [
  ...PREFIX_ENTRIES,
  ["left", "start"],
  ["right", "end"],
];
const DIRECTION_VARIANT_RE = /(?:^|:)(?:rtl|ltr):/u;

function replacementFor(token: string, checkInsets: boolean): string | null {
  const variant = tailwindVariantPrefix(token);
  if (DIRECTION_VARIANT_RE.test(variant)) return null;
  const raw = token.slice(variant.length);
  const prefix = raw.startsWith("!") ? "!" : "";
  const suffix = raw.endsWith("!") ? "!" : "";
  const signed = raw.slice(prefix.length, suffix === "" ? undefined : -1);
  const sign = signed.startsWith("-") ? "-" : "";
  const base = signed.slice(sign.length);
  let logical = EXACT[base];
  for (const [physical, replacement] of checkInsets ? INSET_PREFIX_ENTRIES : PREFIX_ENTRIES) {
    if (base === physical || base.startsWith(`${physical}-`)) {
      logical = replacement + base.slice(physical.length);
      break;
    }
  }
  return logical === undefined
    ? null
    : variant + prefix + sign + logical + suffix;
}

export default defineRule({
  meta: {
    defaultOptions: [{ enabled: true, checkInsets: false, allowUtilities: [] }],
    type: "suggestion",
    docs: {
      description: "Prefer logical Tailwind utilities in explicitly opted-in bidirectional interfaces.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          enabled: { description: "Enable replacement of physical direction utilities with logical equivalents.", type: "boolean" },
          checkInsets: { description: "Include physical inset utilities in direction checks.", type: "boolean" },
          allowUtilities: { description: "Physical utility names allowed without a logical replacement.",
            type: "array",
            items: { type: "string" },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      physicalUtility:
        "Use '{{replacement}}' instead of '{{utility}}' in this bidirectional UI, or explicitly allow intentional physical placement.",
    },
  },
  createOnce(context) {
    let options: Options | undefined;
    return {
      before() {
        options = context.options[0] as Options | undefined;
        const file = { filename: context.filename, cwd: context.cwd };
        if (
          options?.enabled === false ||
          isGeneratedFile(file, context.sourceCode.text) ||
          isTestFile(file) ||
          isStoryFile(file)
        ) return false;
        return undefined;
      },
      JSXOpeningElement(node) {
        const value = attributeText(node, "className");
        if (value === null) return;
        const attribute = node.attributes.findLast(
          (entry) =>
            entry.type === "JSXAttribute" &&
            entry.name.type === "JSXIdentifier" &&
            entry.name.name === "className",
        );
        if (attribute === undefined) return;
        const utilities: string[] = [];
        const replacements: string[] = [];
        for (const utility of new Set(classTokens(value))) {
          const base = utility.slice(tailwindVariantPrefix(utility).length);
          if (options?.allowUtilities?.includes(base)) continue;
          const replacement = replacementFor(
            utility,
            options?.checkInsets ?? false,
          );
          if (replacement !== null) {
            utilities.push(utility);
            replacements.push(replacement);
          }
        }
        if (utilities.length > 0)
          context.report({
            node: attribute,
            messageId: "physicalUtility",
            data: {
              utility: utilities.join(" "),
              replacement: replacements.join(" "),
            },
          });
      },
    };
  },
});
