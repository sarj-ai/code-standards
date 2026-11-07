/**
 * @fileoverview directive-require-description — every directive comment carries a `--` description.
 *
 * Port of `@eslint-community/eslint-comments/require-description` 4.8.1 that
 * also reads `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveComments, directiveLocation, eslintSpelling } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-require-description";

interface RuleOptions {
  readonly ignore?: readonly string[];
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Require a `--` description on every directive comment, `eslint-*` or `oxlint-*`.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          ignore: {
            description: "Directive kinds that need no description; an `oxlint-*` directive follows its `eslint-*` kind.",
            type: "array",
            items: {
              enum: [
                "eslint",
                "eslint-disable",
                "eslint-disable-line",
                "eslint-disable-next-line",
                "eslint-enable",
                "eslint-env",
                "exported",
                "global",
                "globals",
              ],
            },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      missingDescription:
        "Unexpected undescribed directive comment. Include descriptions to explain why the comment is necessary.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const ignored = new Set((context.options[0] as RuleOptions | undefined)?.ignore ?? []);
        const { sourceCode } = context;
        for (const directive of directiveComments(sourceCode)) {
          if (ignored.has(eslintSpelling(directive.kind)) || directive.description !== "") continue;
          context.report({ loc: directiveLocation(sourceCode, directive.comment), messageId: "missingDescription" });
        }
      },
    };
  },
});
