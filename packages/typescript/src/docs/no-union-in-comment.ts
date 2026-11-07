/** @fileoverview no-union-in-comment — the documentation and executable examples of `@sarj/no-union-in-comment`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNION_IN_COMMENT_DOCUMENTATION = {
  summary: "Flag a comment that lists a `string` field's allowed values instead of the type listing them.",
  rationale: "A broad string annotation does not express a closed set documented beside it.",
  remediation: "If the list is exhaustive, express it as a string-literal union; keep examples and runtime constraints documented separately.",
  category: "maintainability",
  autofix: "safe",
  limitations: ["Only bare quoted-value lists directly attached to explicitly annotated string declarations are inspected. Unknown schema builders and runtime validation are not inferred.",
    "Automatic fixes remove only the broad string member from an unused private unmerged interface/object alias whose existing quoted literal branches exactly match the adjacent comment's set. Authored literal branches, nullability and the comment are retained. Bare string declarations, observed/public types, heritage, generics, dependent this, computed/indexed members, escapes and comments inside the changed union remain manual."],
  examples: [
    {
      id: "literal-union",
      title: "Encode allowed values in the type",
      outcome: "no-match",
      files: [{ path: "src/record.ts", source: "interface R { kind: 'aa' | 'bb'; }" }],
      focusPath: "src/record.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "comment-only-union",
      title: "Do not leave allowed values in a comment",
      outcome: "match",
      files: [{ path: "src/record.ts", source: "interface R {\n  kind: string; // 'aa' | 'bb'\n}" }],
      focusPath: "src/record.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Keep the literal contract already authored beside its exact comment",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "export {}; interface Choice { kind: string | 'aa' | 'bb'; // 'aa' | 'bb'\n}" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "export {}; interface Choice { kind: 'aa' | 'bb'; // 'aa' | 'bb'\n}" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
