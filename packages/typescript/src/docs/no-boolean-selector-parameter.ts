/** @fileoverview no-boolean-selector-parameter — the documentation and executable examples of `@sarj/no-boolean-selector-parameter`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_BOOLEAN_SELECTOR_PARAMETER_DOCUMENTATION = {
  summary:
    "Prefer intention-revealing operations over a boolean parameter selecting between actions.",
  rationale:
    "A positional boolean hides which operation a caller requests. Splitting independent actions can make that intent explicit, while boolean data, pure mappings and externally required callback or method contracts remain valid.",
  remediation:
    "Consider separate named operations or an explicit domain mode. Review the public API and its callers manually; preserve required callback, setter and inherited contracts instead of wrapping them solely to silence the warning.",
  category: "maintainability",
  defaultLevel: "warning",
  autofix: "safe",
  limitations: [
    "Requires type information. Checks an owned single-statement if/else, returned conditional or conditional expression statement, and expression-bodied arrow conditionals. Only a direct broad-boolean parameter or its negation is considered; optional, nullable, literal-only, generic, destructured and indirect predicate conditions are excluded.",
    "Preserves setters, pure mappings, selected pure data passed to one stable lexical operation or assigned to one simple target, independently authored callable and inherited member contracts, inline callbacks, and statically proven named callback references. Independent helpers remain checked in JSX files; callback identity is established from references rather than handler names.",
    "The block-body detector preserves the existing literal on[A-Z] object-property exemption; the concise-arrow extension does not infer a callback contract from that name. Multi-statement bodies, short-circuit guards, local parameter aliases and arbitrary control flow are not inferred. Noncomputed property reads count as data without proving getter effects; computed reads remain outside that exemption, including literal keys. Side-effect detection does not prove whether a called function is pure, and a warning requires manual design review. Generated files are excluded; tests remain checked.",
    "Automatic fixes only reuse two already authored private zero-argument ordinary operations returning primitive string literals. A complete comment-free four-declaration module must contain those operations, one private const broad-boolean arrow selecting their direct calls, and one exported zero-argument ordinary function with an explicit string-array return that calls the selector exclusively with literal true and false. Calls are routed to the existing named operations and the exclusively used selector declaration is removed. All other APIs, callbacks, dynamic arguments, contracts and operation bodies remain manual.",
  ],
  references: [
    "https://understandlegacycode.com/blog/what-is-wrong-with-boolean-parameters/",
    "https://martinfowler.com/bliki/FlagArgument.html",
  ],
  examples: [
    {
      id: "concise-boolean-dispatch",
      title: "Name the selected operation explicitly",
      outcome: "match",
      files: [
        {
          path: "src/book.ts",
          source:
            "const book = (premium: boolean) => premium ? premiumBook() : regularBook();",
        },
      ],
      focusPath: "src/book.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "boolean-value-mapping",
      title: "Boolean data may select a pure value",
      outcome: "no-match",
      files: [
        {
          path: "src/label.ts",
          source:
            'function label(enabled: boolean) { if (enabled) { return "Enabled"; } else { return "Disabled"; } }',
        },
      ],
      focusPath: "src/label.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Call the already named selected operations",
      outcome: "match",
      files: [
        {
          path: "src/book.ts",
          source:
            "function premiumBook() { return 'premium'; }\nfunction regularBook() { return 'regular'; }\nconst book = (premium: boolean) => premium ? premiumBook() : regularBook();\nexport function choices(): string[] { return [book(true), book(false), book(true)]; }",
        },
      ],
      fixedFiles: [
        {
          path: "src/book.ts",
          source:
            "function premiumBook() { return 'premium'; }\nfunction regularBook() { return 'regular'; }\nexport function choices(): string[] { return [premiumBook(), regularBook(), premiumBook()]; }",
        },
      ],
      focusPath: "src/book.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
