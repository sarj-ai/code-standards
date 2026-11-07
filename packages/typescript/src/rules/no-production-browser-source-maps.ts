/**
 * @fileoverview no-production-browser-source-maps — Next.js production browser source maps expose application source.
 *
 * Port of the 18.x `no-production-browser-source-maps` rule. Same
 * algorithm; the filename gate runs in `before()`.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-production-browser-source-maps.test.ts
 */

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";
import { canAutofixNextConfigLiteral, exportedNextConfigProperty } from "../utils/exported-next-config-property.js";

const NAME = "no-production-browser-source-maps";
const NEXT_CONFIG_RE = /(?:^|\/)next\.config\.[cm]?[jt]s$/;

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: { description: "Next.js production browser source maps expose application source", url: docsUrl(NAME) },
    schema: [],
    messages: {
      noProductionBrowserSourceMaps:
        "Do not publish production browser source maps. Upload private maps to your monitoring service instead.",
    },
  },
  createOnce(context) {
    return {
      before(): boolean | void {
        if (!NEXT_CONFIG_RE.test(context.filename.replaceAll("\\", "/"))) return false;
      },
      "Program:exit"(): void {
        const { sourceCode } = context;
        const node = exportedNextConfigProperty(sourceCode, ["productionBrowserSourceMaps"]);
        if (node === null || node.value.type !== "Literal" || node.value.value !== true) return;
        const value = node.value;
        context.report({
          node,
          messageId: "noProductionBrowserSourceMaps",
          ...(canAutofixNextConfigLiteral(sourceCode) && { fix: (fixer) => fixer.replaceText(value, "false") }),
        });
      },
    };
  },
});
