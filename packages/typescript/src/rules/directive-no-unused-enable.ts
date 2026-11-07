/**
 * @fileoverview directive-no-unused-enable — no enable directive for rules that are not disabled.
 *
 * Port of `@eslint-community/eslint-comments/no-unused-enable` 4.8.1 that also
 * reads `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveAreas, ruleIdLocation } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-no-unused-enable";

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow `eslint-enable` and `oxlint-enable` directives for rules that are not disabled.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      unused: "Rules are re-enabled but those have not been disabled.",
      unusedRule: "'{{ruleId}}' rule is re-enabled but it has not been disabled.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const { sourceCode } = context;
        for (const { comment, ruleId } of directiveAreas(sourceCode).unusedEnables) {
          context.report({
            loc: ruleIdLocation(sourceCode, comment, ruleId),
            ...(ruleId === null ? { messageId: "unused" } : { messageId: "unusedRule", data: { ruleId } }),
          });
        }
      },
    };
  },
});
