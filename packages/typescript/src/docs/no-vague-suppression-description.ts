/** @fileoverview no-vague-suppression-description — the documentation and executable examples of `@sarj/no-vague-suppression-description`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_VAGUE_SUPPRESSION_DESCRIPTION_DOCUMENTATION = {
  summary:
    "Require suppression descriptions to name the concrete mismatch or invariant instead of a generic non-reason.",
  rationale:
    "Generic phrases satisfy require-description mechanically while leaving reviewers unable to audit the risk or remove stale debt.",
  remediation:
    "Name the exact type/runtime mismatch, external contract, or safety invariant that makes this suppression acceptable.",
  category: "maintainability",
  limitations: [
    "Only `eslint-disable*` and `oxlint-disable*` comments and TypeScript expect-error directives are checked.",
    "The rule uses a small anchored vocabulary and does not score prose quality generally.",
    "Descriptions outside that exact vocabulary are excluded; an unflagged reason is not proof of a justified suppression. Missing descriptions remain owned by the upstream description requirement. Explicit path exclusions own generated-source boundaries; a source marker does not waive suppression accountability.",
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
            "function requestId(response: object) {\n  // @ts-expect-error -- vendor types omit the runtime requestId field\n  return response.requestId;\n}",
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
          source:
            "function requestId(response: object) {\n  // @ts-expect-error -- false positive\n  return response.requestId;\n}",
        },
      ],
      focusPath: "src/adapter.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
