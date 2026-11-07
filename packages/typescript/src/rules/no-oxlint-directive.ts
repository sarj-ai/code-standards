/**
 * @fileoverview no-oxlint-directive — suppress diagnostics with `eslint-*` directives, never `oxlint-*` ones.
 *
 * Oxlint honors both spellings. One spelling keeps every suppression findable
 * with one search and reviewable the same way. The fix rewrites the prefix and
 * keeps the rule list and description.
 */

import type { Fixer } from "@oxlint/plugins";

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "no-oxlint-directive";

// Oxlint's own directive grammar: the keyword opens the comment and ends at whitespace or the comment's end.
const OXLINT_DIRECTIVE_RE = /^(\s*)oxlint-(disable-next-line|disable-line|disable|enable)(?=\s|$)/u;

export default defineRule({
  meta: {
    type: "problem",
    fixable: "code",
    docs: {
      description: "Write every suppression directive with the `eslint-*` spelling.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      oxlintDirective:
        "Use `eslint-{{directive}}` instead of `oxlint-{{directive}}`; suppression directives use one spelling.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        for (const comment of context.sourceCode.getAllComments()) {
          const match = OXLINT_DIRECTIVE_RE.exec(comment.value);
          if (match === null) continue;
          const [, leading = "", directive = ""] = match;
          // `//` and `/*` both open with two characters before the comment value.
          const start = comment.range[0] + 2 + leading.length;
          context.report({
            loc: comment.loc,
            messageId: "oxlintDirective",
            data: { directive },
            fix: (fixer: Fixer) => fixer.replaceTextRange([start, start + "oxlint".length], "eslint"),
          });
        }
      },
    };
  },
});
