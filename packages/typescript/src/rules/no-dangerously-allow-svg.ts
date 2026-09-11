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
  summary: "Next.js image configuration enables SVG rendering without the required response hardening",
  rationale:
    "SVG files can contain scripts and other active content; enabling dangerouslyAllowSVG makes the image optimizer serve that content from the application origin.",
  remediation:
    "Keep dangerouslyAllowSVG disabled. If SVG optimization is required, retain attachment disposition and set the image Content-Security-Policy to `script-src 'none'; sandbox;`.",
  category: "security",
  limitations: [
    "Only literal effective properties of a directly exported object, unescaped const alias, or isolated module.exports object are analyzed. Wrappers, factories, spreads, computed keys, dynamic policies and mutations are not inferred.",
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

function literalString(node: ReturnType<typeof exportedNextConfigProperty>): string | null {
  if (node?.value.type === "Literal" && typeof node.value.value === "string") return node.value.value;
  if (node?.value.type === "TemplateLiteral" && node.value.expressions.length === 0) return node.value.quasis[0]?.value.cooked ?? null;
  return null;
}

function hasHardenedSvgPolicy(policy: string): boolean {
  const directives = policy
    .split(";")
    .map((part) => part.trim().split(/\s+/u).filter(Boolean))
    .filter((parts) => parts.length > 0);
  const scriptSources = directives.filter(([name]) => name?.toLowerCase() === "script-src");
  const sandboxes = directives.filter(([name]) => name?.toLowerCase() === "sandbox");
  const scriptSource = scriptSources[0];
  const sandbox = sandboxes[0];
  return (
    scriptSources.length === 1 &&
    sandboxes.length === 1 &&
    scriptSource?.length === 2 &&
    scriptSource[1]?.toLowerCase() === "'none'" &&
    sandbox?.length === 1
  );
}

export default createRule<Options, MessageIds>({
  name: "no-dangerously-allow-svg",
  documentation: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION,
  meta: {
    type: "problem",
    docs: { description: NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION.summary },
    schema: [],
    messages: {
      noDangerouslyAllowSvg:
        "Do not enable dangerouslyAllowSVG without a script-blocking sandbox policy and attachment disposition. SVG can carry active content served from the application origin.",
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
          const disposition = exportedNextConfigProperty(context.sourceCode, ["images", "contentDispositionType"]);
          const policy = literalString(
            exportedNextConfigProperty(context.sourceCode, ["images", "contentSecurityPolicy"]),
          );
          const attachmentDisposition = disposition === null || literalString(disposition) === "attachment";
          if (attachmentDisposition && policy !== null && hasHardenedSvgPolicy(policy)) return;
          context.report({ node, messageId: "noDangerouslyAllowSvg" });
        }
      },
    };
  },
});
