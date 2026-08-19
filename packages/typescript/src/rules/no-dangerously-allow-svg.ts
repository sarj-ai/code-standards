/**
 * @fileoverview no-dangerously-allow-svg — unsafe SVG delivery from Next Image can execute active content.
 *
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-dangerously-allow-svg.test.ts
 */

import { type TSESTree } from "@typescript-eslint/utils";

import { createRule, type RuleDocumentation } from "./_docs.js";

type MessageIds = "noDangerouslyAllowSvg";
type Options = readonly [];

const NEXT_CONFIG_RE = /(?:^|\/)next\.config\.[cm]?[jt]s$/;

export const noDangerouslyAllowSvgDocumentation = {
  summary: "Next.js image configuration enables unsanitized SVG rendering",
  rationale:
    "SVG files can contain scripts and other active content; enabling dangerouslyAllowSVG makes the image optimizer serve that content from the application origin.",
  remediation:
    "Keep dangerouslyAllowSVG disabled. If SVG delivery is unavoidable, use a separately reviewed asset path with restrictive Content-Disposition and Content-Security-Policy headers.",
  category: "security",
  limitations: [
    "Only a literal true assigned to dangerouslyAllowSVG in a next.config source file is reported; computed or imported configuration is intentionally not inferred.",
  ],
  examples: [
    {
      id: "svg-disabled",
      title: "Keep active SVG delivery disabled",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: false } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "svg-enabled",
      title: "Do not enable active SVG delivery",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true } };\n" }],
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
  name: "no-dangerously-allow-svg",
  documentation: noDangerouslyAllowSvgDocumentation,
  meta: {
    type: "problem",
    docs: { description: noDangerouslyAllowSvgDocumentation.summary },
    schema: [],
    messages: {
      noDangerouslyAllowSvg:
        "Do not enable dangerouslyAllowSVG. SVG can carry active content served from the application origin.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (!NEXT_CONFIG_RE.test(context.filename.replaceAll("\\", "/"))) return {};
    return {
      Property(node): void {
        if (
          propertyName(node) === "dangerouslyAllowSVG" &&
          node.value.type === "Literal" &&
          node.value.value === true
        ) {
          context.report({ node, messageId: "noDangerouslyAllowSvg" });
        }
      },
    };
  },
});
