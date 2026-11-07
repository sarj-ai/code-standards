/**
 * @fileoverview directive-no-duplicate-disable — no disable directive for a rule that is already disabled.
 *
 * Port of `@eslint-community/eslint-comments/no-duplicate-disable` 4.8.1 that
 * also reads `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveAreas, ruleIdLocation } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-no-duplicate-disable";

export default defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow `eslint-disable` and `oxlint-disable` directives for rules that are already disabled there.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      duplicate: "All rules have been disabled already.",
      duplicateRule: "'{{ruleId}}' rule has been disabled already.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const { sourceCode } = context;
        for (const { comment, ruleId } of directiveAreas(sourceCode).duplicateDisables) {
          context.report({
            loc: ruleIdLocation(sourceCode, comment, ruleId),
            ...(ruleId === null ? { messageId: "duplicate" } : { messageId: "duplicateRule", data: { ruleId } }),
          });
        }
      },
    };
  },
});
