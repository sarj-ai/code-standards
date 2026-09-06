/**
 * @fileoverview no-dangerously-allow-svg — unsafe SVG delivery from Next Image can execute active content.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-dangerously-allow-svg.test.ts
 */

import { createRule, type RuleDocumentation } from "./_docs.js";
import { exportedNextConfigProperty } from "./_exported-next-config-property.js";

type MessageIds = "noDangerouslyAllowSvg";
type Options = readonly [];

const NEXT_CONFIG_RE = /(?:^|\/)next\.config\.[cm]?[jt]s$/;

export const NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION = {
  summary: "Next.js image configuration enables unsanitized SVG rendering",
  rationale:
    "SVG files can contain scripts and other active content; enabling dangerouslyAllowSVG makes the image optimizer serve that content from the application origin.",
  remediation:
    "Keep dangerouslyAllowSVG disabled. If SVG delivery is unavoidable, use a separately reviewed asset path with restrictive Content-Disposition and Content-Security-Policy headers.",
  category: "security",
  limitations: [
    "Only a literal true in the effective images property of a directly exported object, unescaped const alias, or isolated module.exports object is reported. Wrappers, factories, spreads, computed keys and mutations are not inferred.",
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

export default createRule<Options, MessageIds>({
  name: "no-dangerously-allow-svg",
  documentation: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION.summary },
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
      "Program:exit"(): void {
        const node = exportedNextConfigProperty(context.sourceCode, ["images", "dangerouslyAllowSVG"]);
        if (
          node !== null &&
          node.value.type === "Literal" &&
          node.value.value === true
        ) {
          context.report({ node, messageId: "noDangerouslyAllowSvg" });
        }
      },
    };
  },
});
