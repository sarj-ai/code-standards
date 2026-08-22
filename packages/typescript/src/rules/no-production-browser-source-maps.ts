/**
 * @fileoverview no-production-browser-source-maps — public source maps disclose shipped application source.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-production-browser-source-maps.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "noProductionBrowserSourceMaps";
type Options = readonly [];

const NEXT_CONFIG_RE = /(?:^|\/)next\.config\.[cm]?[jt]s$/;

export const NO_PRODUCTION_BROWSER_SOURCE_MAPS_DOCUMENTATION = {
  summary: "Next.js production browser source maps expose application source",
  rationale:
    "Next.js production browser source maps publish original client source and implementation details to every browser that can load the deployment.",
  remediation:
    "Leave productionBrowserSourceMaps disabled and upload private source maps directly to the error-monitoring service during the build.",
  category: "security",
  limitations: [
    "Only a literal true assigned in a next.config source file is reported; computed or imported configuration is intentionally not inferred.",
  ],
  examples: [
    {
      id: "private-source-maps",
      title: "Keep browser source maps private",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { productionBrowserSourceMaps: false };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "public-source-maps",
      title: "Do not publish production browser source maps",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { productionBrowserSourceMaps: true };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

function propertyName(node: TSESTree.Property): string | null {
  if (!node.computed && node.key.type === "Identifier") return node.key.name;
  if (node.key.type === "Literal" && typeof node.key.value === "string") return node.key.value;
  return null;
}

export default createRule<Options, MessageIds>({
  name: "no-production-browser-source-maps",
  documentation: NO_PRODUCTION_BROWSER_SOURCE_MAPS_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_PRODUCTION_BROWSER_SOURCE_MAPS_DOCUMENTATION.summary },
    schema: [],
    messages: {
      noProductionBrowserSourceMaps:
        "Do not publish production browser source maps. Upload private maps to your monitoring service instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!NEXT_CONFIG_RE.test(context.filename.replaceAll("\\", "/"))) return {};
    return {
      Property(node): void {
        if (
          propertyName(node) === "productionBrowserSourceMaps" &&
          node.value.type === "Literal" &&
          node.value.value === true
        ) {
          context.report({ node, messageId: "noProductionBrowserSourceMaps" });
        }
      },
    };
  },
});
