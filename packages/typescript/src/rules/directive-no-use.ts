/**
 * @fileoverview directive-no-use — only the allowed kinds of directive comments.
 *
 * Port of `@eslint-community/eslint-comments/no-use` 4.8.1 that also reads
 * `oxlint-*` directives (see `../utils/directive-comments.ts`).
 */

import { defineRule } from "../types.js";
import { directiveComments, directiveLocation, eslintSpelling } from "../utils/directive-comments.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "directive-no-use";

interface RuleOptions {
  readonly allow?: readonly string[];
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Disallow directive comments, `eslint-*` or `oxlint-*`, except the allowed kinds.",
      url: docsUrl(NAME),
    },
    schema: [
      {
        type: "object",
        properties: {
          allow: {
            description: "Directive kinds to allow, such as `eslint-disable-next-line`; an `oxlint-*` directive follows its `eslint-*` kind.",
            type: "array",
            items: { type: "string" },
            uniqueItems: true,
          },
        },
        additionalProperties: false,
      },
    ],
    messages: {
      disallow: "Unexpected `{{kind}}` directive comment.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        const allowed = new Set((context.options[0] as RuleOptions | undefined)?.allow ?? []);
        const { sourceCode } = context;
        for (const directive of directiveComments(sourceCode)) {
          if (allowed.has(eslintSpelling(directive.kind))) continue;
          context.report({
            loc: directiveLocation(sourceCode, directive.comment),
            messageId: "disallow",
            data: { kind: directive.kind },
          });
        }
      },
    };
  },
});
