/**
 * @fileoverview no-typed-doc-sections — typed signatures do not need parameter or return tables.
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-typed-doc-sections.test.ts
 */

import { createRule } from "./_docs.js";
import { documentsTypedFunction, proseGroups } from "./_prose-budget.js";

type MessageIds = "typedSection";
type Options = readonly [];

export default createRule<Options, MessageIds>({
  name: "no-typed-doc-sections",
  meta: {
    type: "suggestion",
    docs: { description: "Reject parameter and return JSDoc tags on fully typed functions." },
    schema: [],
    messages: {
      typedSection: "Typed JSDoc repeats parameters or returns — delete the tags and improve names or types instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode)) {
          if (group.hasTypedTags && documentsTypedFunction(context.sourceCode, group.comment)) {
            context.report({ node: group.comment, messageId: "typedSection" });
          }
        }
      },
    };
  },
});
