/**
 * @fileoverview no-typed-doc-sections — typed signatures do not need parameter or return tables.
 * Examples: https://github.com/sarj-ai/standards/blob/main/packages/typescript/tests/rules/no-typed-doc-sections.test.ts
 */

import { createRule, type RuleDocumentation } from "./_docs.js";
import { documentsTypedFunction, proseGroups } from "./_prose-budget.js";

type MessageIds = "typedSection";
type Options = readonly [];

export const noTypedDocSectionsDocumentation = {
  summary: "Reject typed-signature repetition while preserving behavior that types cannot express.",
  rationale:
    "Parameter and return tags repeat typed signatures and can drift without adding runtime behavior or constraints.",
  remediation: "Remove repeated parameter and return tags; retain documentation for behavior, failures, and external contracts.",
  category: "maintainability",
  limitations: ["Parameter and return tags are reported only when the documented function has corresponding explicit TypeScript types."],
  examples: [
    {
      id: "behavioral-documentation",
      title: "Keep behavior that the signature cannot express",
      outcome: "no-match",
      files: [{ path: "src/client.ts", source: "/** Retries when the vendor returns 429. */\nexport function fetchValue(id: string): number { return 1; }" }],
      focusPath: "src/client.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "repeated-typed-sections",
      title: "Do not restate typed parameters and returns",
      outcome: "match",
      files: [{ path: "src/client.ts", source: "/** @param id external identifier\n * @returns the value\n */\nexport function fetchValue(id: string): number { return 1; }" }],
      focusPath: "src/client.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-typed-doc-sections",
  documentation: noTypedDocSectionsDocumentation,
  meta: {
    type: "suggestion",
    docs: { description: "Reject typed-signature repetition while preserving behavior that types cannot express." },
    schema: [],
    messages: {
      typedSection: "Typed JSDoc repeats parameters or returns — delete the tags and improve names or types instead.",
    },
  },
  defaultOptions: [],
  create(context) {
    return {
      Program(): void {
        for (const group of proseGroups(context.filename, context.sourceCode, true)) {
          if (group.hasTypedTags && documentsTypedFunction(context.sourceCode, group.comment)) {
            context.report({ node: group.comment, messageId: "typedSection" });
          }
        }
      },
    };
  },
});
