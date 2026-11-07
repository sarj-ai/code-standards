/** @fileoverview require-static-next-matcher — the documentation and executable examples of `@sarj/require-static-next-matcher`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_STATIC_NEXT_MATCHER_DOCUMENTATION = {
  summary:
    "Require Next.js middleware and proxy matcher configuration to contain only build-time literals.",
  rationale:
    "Next.js must statically analyze matcher values at build time; computed values are ignored.",
  remediation:
    "Write matcher strings, arrays, and object fields as literals in the exported config.",
  category: "correctness",
  autofix: "safe",
  limitations: [
    "Only directly exported matcher configuration in middleware/proxy entry files is inspected. Literal matcher validity is left to Next.js; this rule checks static syntax, not the complete framework schema.",
    "Automatic edits only inline an existing private unannotated const string literal in a complete two-statement module whose only export is a const config containing that sole matcher reference. The exclusively inlined binding is removed. Imports, comments, arrays, other references or properties, wrappers, annotations, mutable bindings and computed keys remain manual.",
  ],
  references: [
    "https://nextjs.org/docs/app/api-reference/file-conventions/proxy",
  ],
  examples: [
    {
      id: "literal-matcher",
      title: "Use a literal matcher",
      outcome: "no-match",
      files: [
        {
          path: "src/middleware.ts",
          source: 'export const config = { matcher: "/api/:path*" };',
        },
      ],
      focusPath: "src/middleware.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "computed-matcher",
      title: "Do not compute the matcher",
      outcome: "match",
      files: [
        {
          path: "src/middleware.ts",
          source:
            'const matcher = "/api/:path*"; export const config = { matcher };',
        },
      ],
      focusPath: "src/middleware.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Inline the existing private literal route",
      outcome: "match",
      files: [
        {
          path: "src/middleware.ts",
          source:
            'const matcher = "/api/:path*"; export const config = { matcher };',
        },
      ],
      fixedFiles: [
        {
          path: "src/middleware.ts",
          source: 'export const config = { matcher: "/api/:path*" };',
        },
      ],
      focusPath: "src/middleware.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
