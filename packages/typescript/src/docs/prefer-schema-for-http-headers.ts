import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SCHEMA_FOR_HTTP_HEADERS_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Prefer named Zod contracts for scalar parsing of native HTTP headers.",
  rationale: "Ad hoc scalar casts scatter HTTP admission grammar, fallback defaults and failures instead of naming the parsed fields.",
  remediation: "Declare a named Zod header contract. Preserve scalar grammar, missing-value defaults, precedence and error timing; never replace a signature or opaque transport read with coercion.",
  category: "maintainability",
  limitations: [
    "Builtin Number, Boolean, parseInt and parseFloat calls consuming literal-key native Request/Response.headers or Headers.get values also report. Stable const aliases and scalar fallback expressions retain provenance. Prefer a named Zod contract while preserving parsing grammar, defaults, precedence and failures. Textual/signature reads, custom parsers, dynamic keys, unknown providers, mutable bindings and shadowed native globals abstain. One warning covers a nested scalar fallback; no automatic fix is provided.",
    "Uses the existing API payload rule's native response and stable binding proofs. A source-text prefilter only avoids starting visitors on files without scalar/get candidates. No type service, package installation or provider import is performed. Native member mutation, imported Request/Headers implementations, destructured header methods, indirect coercion and custom namespaces require review and are outside this bounded rule. Generated, declaration, script and test files are excluded.",
    "Warning-stage guidance, independent of the existing JSON payload ERROR. No automatic fix is offered. Ordinary exact-code ESLint suppression applies.",
  ],
  examples: [
    {
      id: "scalar-http-header", scenarioId: "http-header-contract",
      title: "A scalar cast leaves the header contract implicit",
      outcome: "match",
      files: [
        {
          path: "src/headers.ts",
          source:
            "function attempt(request: Request) { return Number(request.headers.get('x-attempt') ?? '1'); }",
        },
      ],
      focusPath: "src/headers.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "named-zod-header", scenarioId: "http-header-contract",
      title: "A named Zod schema owns scalar parsing",
      outcome: "no-match",
      files: [
        {
          path: "src/headers.ts",
          source:
            "import { z } from 'zod'; const Attempt = z.string().default('1').transform(Number); function attempt(request: Request) { return Attempt.parse(request.headers.get('x-attempt') ?? undefined); }",
        },
      ],
      installedDependencies: [{ module: "zod", version: "4.6.7" }],
      focusPath: "src/headers.ts",
      expectedCount: 0,
      public: true,
    },


  ],
} as const satisfies RuleDocumentation;
