/**
 * @fileoverview prefer-single-sentence-comment — two sentences should be reduced to one.
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/prefer-single-sentence-comment.test.ts
 */

import { createRule } from "./_docs.js";
import { proseGroups, sentenceUnits } from "./_prose-budget.js";

type MessageIds = "preferOneSentence";
type Options = readonly [];

export default createRule<Options, MessageIds>({
  name: "prefer-single-sentence-comment",
  meta: {
    type: "suggestion",
    docs: { description: "Prefer one sentence and self-documenting code over a two-sentence comment." },
    schema: [],
    messages: {
      preferOneSentence: "Two-sentence comment — prefer one sentence and self-documenting code.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode)) {
          if (!group.hasTypedTags && sentenceUnits(group.text) === 2) {
            context.report({ node: group.comment, messageId: "preferOneSentence" });
          }
        }
      },
    };
  },
});
