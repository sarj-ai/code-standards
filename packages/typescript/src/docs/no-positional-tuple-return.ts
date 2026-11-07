/** @fileoverview no-positional-tuple-return — the documentation and executable examples of `@sarj/no-positional-tuple-return`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_POSITIONAL_TUPLE_RETURN_DOCUMENTATION = {
  summary:
    "Disallow returning a multi-field tuple from a named function; return a named object so call sites cannot mismatch slots.",
  rationale:
    "Tuple fields are identified only by position, so reordering can preserve types while changing meaning.",
  remediation: "Return an object whose property names describe each value.",
  category: "maintainability",
  autofix: "safe",
  limitations: [
    "Declared or syntax-proven multi-field tuple returns on named functions and public type surfaces are inspected; anonymous inline callbacks and syntax-proven TanStack Query key factories are excluded.",
    "Automatic edits only migrate a private zero-argument ordinary helper returning two labeled primitive literal fields, with one exported zero-argument ordinary caller that immediately destructures those same names and returns the already declared matching public object contract. The complete module must contain only those two functions without comments or other references. Existing labels and the public object type supply every field name; primitive evaluation order and fresh public results are retained. This subset assumes the canonical Array iterator. Public tuple APIs, aliases, callbacks, defaults, generics, rest/optional fields, unsafe property names and other callers remain manual.",
  ],
  examples: [
    {
      id: "named-object-return",
      title: "Return named fields",
      outcome: "no-match",
      files: [
        {
          path: "src/download.ts",
          source:
            "export function download(): { body: string; status: number } { return impl(); }",
        },
      ],
      focusPath: "src/download.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "tuple-return",
      title: "Do not expose positional fields",
      outcome: "match",
      files: [
        {
          path: "src/download.ts",
          source:
            "export function download(): [string, number] { return impl(); }",
        },
      ],
      focusPath: "src/download.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "query-key-outer-const",
      scenarioId: "query-key-const-anchor",
      title: "Inherit the query-key anchor const context",
      outcome: "no-match",
      files: [
        {
          path: "src/keys.ts",
          source:
            "const userKeys = { all: ['users'], detail: (id: string) => [...userKeys.all, id] as const } as const;",
        },
      ],
      focusPath: "src/keys.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mutable-query-key-object",
      scenarioId: "query-key-const-anchor",
      title: "Keep a mutable tuple-return object checked",
      outcome: "match",
      files: [
        {
          path: "src/keys.ts",
          source:
            "const userKeys = { all: ['users'], detail: (id: string) => [...userKeys.all, id] as const };",
        },
      ],
      focusPath: "src/keys.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Reuse the existing named result contract",
      outcome: "match",
      files: [
        {
          path: "src/download.ts",
          source:
            "function download(): [body: string, status: number] { return ['ok', 200]; }\nexport function run(): { body: string; status: number } { const [body, status] = download(); return { body, status }; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/download.ts",
          source:
            "function download(): { body: string; status: number } { return { body: 'ok', status: 200 }; }\nexport function run(): { body: string; status: number } { const { body, status } = download(); return { body, status }; }",
        },
      ],
      focusPath: "src/download.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
