/**
 * @fileoverview no-dangerously-allow-svg — require explicit response hardening for Next Image SVG delivery.
 *
 * Port of the 18.x `no-dangerously-allow-svg` rule. Same algorithm; the
 * filename gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-dangerously-allow-svg.test.ts
 */

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { canAutofixNextConfigLiteral, exportedNextConfigProperty } from "../utils/exported-next-config-property.js";

const NAME = "no-dangerously-allow-svg";
const NEXT_CONFIG_RE = /(?:^|\/)next\.config\.[cm]?[jt]s$/;

function literalString(node: ReturnType<typeof exportedNextConfigProperty>): string | null {
  if (node?.value.type === "Literal" && typeof node.value.value === "string") return node.value.value;
  if (node?.value.type === "TemplateLiteral" && node.value.expressions.length === 0)
    return node.value.quasis[0]?.value.cooked ?? null;
  return null;
}

function hasHardenedSvgPolicy(policy: string): boolean {
  const directives = new Map<string, readonly string[]>();
  for (const part of policy.split(";")) {
    const [name, ...values] = part.split(/[\t\n\f\r ]+/u).filter(Boolean);
    if (name === undefined || !/^[A-Za-z0-9-]+$/u.test(name)) continue;
    const key = name.toLowerCase();
    if (!directives.has(key)) directives.set(key, values);
  }
  const scriptSource = directives.get("script-src");
  const sandbox = directives.get("sandbox");
  return scriptSource?.length === 1 && scriptSource[0]?.toLowerCase() === "'none'" && sandbox?.length === 0;
}

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: { description: "Require an explicit hardening policy for Next Image SVG delivery", url: docsUrl(NAME) },
    schema: [],
    messages: {
      noDangerouslyAllowSvg:
        "SVG opt-in requires a recognized explicit script-blocking sandbox CSP and attachment disposition under this policy.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        if (!NEXT_CONFIG_RE.test(context.filename.replaceAll("\\", "/"))) return false;
      },
      "Program:exit"(): void {
        const { sourceCode } = context;
        const node = exportedNextConfigProperty(sourceCode, ["images", "dangerouslyAllowSVG"]);
        if (node === null || node.value.type !== "Literal" || node.value.value !== true) return;
        const disposition = exportedNextConfigProperty(sourceCode, ["images", "contentDispositionType"]);
        const policy = literalString(exportedNextConfigProperty(sourceCode, ["images", "contentSecurityPolicy"]));
        const attachmentDisposition = disposition === null || literalString(disposition) === "attachment";
        if (attachmentDisposition && policy !== null && hasHardenedSvgPolicy(policy)) return;
        const value = node.value;
        context.report({
          node,
          messageId: "noDangerouslyAllowSvg",
          ...(canAutofixNextConfigLiteral(sourceCode) && { fix: (fixer) => fixer.replaceText(value, "false") }),
        });
      },
    };
  },
});
