/**
 * @fileoverview no-long-comment — three or more sentences exceed the in-code prose budget.
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-long-comment.test.ts
 */

import { createRule } from "./_docs.js";
import { proseGroups, sentenceUnits } from "./_prose-budget.js";

type MessageIds = "tooLong";
type Options = readonly [];

export default createRule<Options, MessageIds>({
  name: "no-long-comment",
  meta: {
    type: "suggestion",
    docs: { description: "Limit in-code prose to two sentences." },
    schema: [],
    messages: {
      tooLong: "Comment exceeds two sentences — keep one local fact and clarify the code itself.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode)) {
          if (!group.hasTypedTags && sentenceUnits(group.text) >= 3) {
            context.report({ node: group.comment, messageId: "tooLong" });
          }
        }
      },
    };
  },
});
