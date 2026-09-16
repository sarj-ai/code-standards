/**
 * @fileoverview prefer-logical-tailwind-utilities — statically proven UI policy violations receive actionable diagnostics.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/prefer-logical-tailwind-utilities.test.ts
 */

import { AST_NODE_TYPES } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";
import { attributeText } from "./_jsx-accessibility.js";
import { isGeneratedFile, isStoryFile, isTestFile } from "./_paths.js";
import { classTokens, tailwindVariantPrefix } from "./_tailwind.js";

type Options = readonly [
  {
    readonly enabled?: boolean;
    readonly checkInsets?: boolean;
    readonly allowUtilities?: readonly string[];
  }?,
];

export const PREFER_LOGICAL_TAILWIND_UTILITIES_DOCUMENTATION = {
  summary:
    "Prefer logical Tailwind utilities in explicitly opted-in bidirectional interfaces.",
  rationale:
    "Physical spacing and alignment remain on the same side when reading direction changes, producing incorrectly mirrored interfaces.",
  remediation:
    "Use the suggested logical utility; retain intentional physical geometry through allowUtilities or a scoped rule override.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Enable this rule only in scopes that support bidirectional layout. Standalone rule activation opts in. Insets require checkInsets:true; explicit rtl:/ltr: variants are exempt. No autofix changes physical coordinates.",
    "Only effective complete static JSX className values are inspected. Dynamic compositions, CSS, class factories and identifier references are not inferred. Tests, stories, fixtures and generated files are excluded.",
  ],
  examples: [
    {
      id: "physical-spacing",
      title: "Mirror layout spacing",
      outcome: "match",
      files: [{ path: "src/layout.tsx", source: '<div className="ml-2" />' }],
      focusPath: "src/layout.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "logical-spacing",
      title: "Use direction-aware spacing",
      outcome: "no-match",
      files: [{ path: "src/layout.tsx", source: '<div className="ms-2" />' }],
      focusPath: "src/layout.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

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

const INSET_PREFIXES: Readonly<Record<string, string>> = {
  ...PREFIXES,
  left: "start",
  right: "end",
};

function replacementFor(token: string, checkInsets: boolean): string | null {
  const variant = tailwindVariantPrefix(token);
  if (/(?:^|:)(?:rtl|ltr):/u.test(variant)) return null;
  const raw = token.slice(variant.length);
  const prefix = raw.startsWith("!") ? "!" : "";
  const suffix = raw.endsWith("!") ? "!" : "";
  const signed = raw.slice(prefix.length, suffix === "" ? undefined : -1);
  const sign = signed.startsWith("-") ? "-" : "";
  const base = signed.slice(sign.length);
  let logical = EXACT[base];
  const mappings = checkInsets ? INSET_PREFIXES : PREFIXES;
  for (const [physical, replacement] of Object.entries(mappings)) {
    if (base === physical || base.startsWith(`${physical}-`)) {
      logical = replacement + base.slice(physical.length);
      break;
    }
  }
  return logical === undefined
    ? null
    : variant + prefix + sign + logical + suffix;
}

export default createRule<Options, "physicalUtility">({
  name: "prefer-logical-tailwind-utilities",
  documentation: PREFER_LOGICAL_TAILWIND_UTILITIES_DOCUMENTATION,
  meta: {
    type: "suggestion",
    docs: {
      description: PREFER_LOGICAL_TAILWIND_UTILITIES_DOCUMENTATION.summary,
    },
    schema: [
      {
        type: "object",
        properties: {
          enabled: { type: "boolean" },
          checkInsets: { type: "boolean" },
          allowUtilities: {
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
  defaultOptions: [{ enabled: true, checkInsets: false, allowUtilities: [] }],
  create(context, [options]) {
    if (
      options?.enabled === false ||
      isGeneratedFile(context.filename, context.sourceCode.text) ||
      isTestFile(context.filename) ||
      isStoryFile(context.filename)
    )
      return {};
    return {
      JSXOpeningElement(node): void {
        const value = attributeText(node, "className");
        if (value === null) return;
        const attribute = node.attributes.findLast(
          (entry) =>
            entry.type === AST_NODE_TYPES.JSXAttribute &&
            entry.name.type === AST_NODE_TYPES.JSXIdentifier &&
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
