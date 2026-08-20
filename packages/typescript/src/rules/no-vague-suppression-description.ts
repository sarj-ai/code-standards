/**
 * @fileoverview no-vague-suppression-description — a suppression reason must name the concrete mismatch or invariant, not merely claim the suppression is needed.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/no-vague-suppression-description.test.ts
 */

import { createRule, type RuleDocumentation } from "./_docs.js";
import { isGeneratedFile } from "./_paths.js";

type MessageIds = "vagueDescription";
type Options = readonly [];

const DIRECTIVE_WITH_DESCRIPTION_RE = /^(?:eslint-(?:disable|disable-next-line|disable-line)\b[^:\n]*?|@ts-expect-error\b)\s*(?::|--)\s*(.+?)\s*$/iu;
const VAGUE_RE = /^(?:needed|required|intentional(?:ly)?|ignore(?:d)?|false positive|type error|typescript|to satisfy (?:the )?(?:linter|typescript|type checker))\.?$/iu;

export const noVagueSuppressionDescriptionDocumentation = {
  summary:
    "Require suppression descriptions to name the concrete mismatch or invariant instead of a generic non-reason.",
  rationale:
    "Generic phrases satisfy require-description mechanically while leaving reviewers unable to audit the risk or remove stale debt.",
  remediation:
    "Name the exact type/runtime mismatch, external contract, or safety invariant that makes this suppression acceptable.",
  category: "maintainability",
  limitations: [
    "Only ESLint disable comments and TypeScript expect-error directives are checked.",
    "The rule uses a small anchored vocabulary and does not score prose quality generally.",
    "Generated files and descriptions containing any concrete context are excluded.",
  ],
  examples: [
    {
      id: "concrete-runtime-mismatch",
      title: "Explain the concrete runtime contract",
      outcome: "no-match",
      files: [
        {
          path: "src/adapter.ts",
          source:
            "// @ts-expect-error -- vendor types omit the runtime requestId field\nreturn response.requestId;",
        },
      ],
      focusPath: "src/adapter.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "generic-suppression-reason",
      title: "Reject a suppression with no auditable reason",
      outcome: "match",
      files: [
        {
          path: "src/adapter.ts",
          source: "// @ts-expect-error -- false positive\nreturn response.requestId;",
        },
      ],
      focusPath: "src/adapter.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createRule<Options, MessageIds>({
  name: "no-vague-suppression-description",
  documentation: noVagueSuppressionDescriptionDocumentation,
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Require suppression descriptions to name the concrete mismatch or invariant instead of a generic non-reason.",
    },
    schema: [],
    messages: {
      vagueDescription:
        "Suppression description `{{description}}` does not explain why the suppressed diagnostic is safe here. Name the concrete type/runtime mismatch, external contract, or invariant.",
    },
  },
  defaultOptions: [],
  create(context) {
    if (isGeneratedFile(context.filename, context.sourceCode.text)) {
      return {};
    }
    return {
      Program(): void {
        for (const comment of context.sourceCode.getAllComments()) {
          const text = comment.value.trim();
          const description = DIRECTIVE_WITH_DESCRIPTION_RE.exec(text)?.[1]?.trim();
          if (description === undefined || !VAGUE_RE.test(description)) continue;
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
