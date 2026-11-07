/**
 * @fileoverview directive-no-restricted-disable — no disable directive may turn off a restricted rule.
 *
 * Port of `@eslint-community/eslint-comments/no-restricted-disable` 4.8.1 that
 * also reads `oxlint-*` directives (see `../utils/directive-comments.ts`).
 * Options are gitignore-style rule ID patterns (see `../utils/rule-id-matcher.ts`).
 */

import { defineRule } from "../types.js";
import { directiveAreas, ruleIdLocation } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";
import { ruleIdMatcher } from "../utils/rule-id-matcher.js";

const NAME = "directive-no-restricted-disable";

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow `eslint-disable` and `oxlint-disable` directives that turn off a restricted rule or every rule.",
      url: docsUrl(NAME),
    },
    schema: {
      type: "array",
      items: { type: "string" },
      uniqueItems: true,
    },
    messages: {
      disallow: "Disabling '{{ruleId}}' is not allowed.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const patterns = context.options as readonly string[];
        if (patterns.length === 0) return;
        const restricted = ruleIdMatcher(patterns);
        const { sourceCode } = context;
        for (const area of directiveAreas(sourceCode).areas) {
          if (area.ruleId !== null && !restricted(area.ruleId)) continue;
          context.report({
            loc: ruleIdLocation(sourceCode, area.comment, area.ruleId),
            messageId: "disallow",
            data: { ruleId: area.ruleId ?? String(patterns) },
          });
        }
      },
    };
  },
});
