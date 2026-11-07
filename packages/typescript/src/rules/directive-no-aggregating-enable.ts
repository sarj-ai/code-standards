/**
 * @fileoverview directive-no-aggregating-enable — one enable directive closes one disable directive.
 *
 * Port of `@eslint-community/eslint-comments/no-aggregating-enable` 4.8.1 that
 * also reads `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveAreas, directiveLocation } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-no-aggregating-enable";

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow one `eslint-enable` or `oxlint-enable` directive closing several disable directives.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      aggregatingEnable:
        "This `eslint-enable` comment affects {{count}} `eslint-disable` comments. An `eslint-enable` comment should be for an `eslint-disable` comment.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const { sourceCode } = context;
        for (const [comment, count] of directiveAreas(sourceCode).closedDisables) {
          if (count < 2) continue;
          context.report({
            loc: directiveLocation(sourceCode, comment),
            messageId: "aggregatingEnable",
            data: { count: String(count) },
          });
        }
      },
    };
  },
});
