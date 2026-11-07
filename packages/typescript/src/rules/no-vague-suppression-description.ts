/**
 * @fileoverview no-vague-suppression-description — suppression descriptions name the concrete mismatch or invariant.
 *
 * Port of the 18.x `no-vague-suppression-description` rule. Same
 * algorithm: one pass over the file's comments from the `Program` visitor; it
 * also reads `oxlint-*` directives.
 */

import { defineRule } from "../types.js";
import { docsUrl } from "../utils/docs-url.js";

const NAME = "no-vague-suppression-description";

const DIRECTIVE_WITH_DESCRIPTION_RE =
  /^(?:eslint|oxlint)-(?:disable|disable-next-line|disable-line)\b[^:\n]*?\s*(?::|--)\s*(.+?)\s*$/iu;
const TS_EXPECT_ERROR_WITH_DESCRIPTION_RE =
  /^@ts-expect-error\b(?:(?:\s*(?::|--)\s*)|\s+)(.+?)\s*$/iu;
const VAGUE_RE =
  /^(?:needed|required|same|n\/a|legacy|intentional(?:ly)?|ignore(?:d)?|false positive|type error|typescript|to satisfy (?:the )?(?:linter|typescript|type checker))\.?$/iu;

function suppressionDescription(text: string): string | undefined {
  return (
    DIRECTIVE_WITH_DESCRIPTION_RE.exec(text)?.[1] ??
    TS_EXPECT_ERROR_WITH_DESCRIPTION_RE.exec(text)?.[1]
  )?.trim();
}

export default defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require suppression descriptions to name the concrete mismatch or invariant instead of a generic non-reason.",
      url: docsUrl(NAME),
    },
    schema: [],
    messages: {
      vagueDescription:
        "Suppression description `{{description}}` does not explain why the suppressed diagnostic is safe here. Name the concrete type/runtime mismatch, external contract, or invariant.",
    },
  },
  createOnce(context) {
    return {
      Program(): void {
        for (const comment of context.sourceCode.getAllComments()) {
          const text = comment.value.trim();
          const description = suppressionDescription(text);
          if (description === undefined || !VAGUE_RE.test(description))
            continue;
          context.report({
            loc: comment.loc,
            messageId: "vagueDescription",
            data: { description },
          });
        }
      },
    };
  },
});
