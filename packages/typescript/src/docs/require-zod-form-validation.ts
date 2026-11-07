/** @fileoverview require-zod-form-validation — the documentation and executable examples of `@sarj/require-zod-form-validation`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_ZOD_FORM_VALIDATION_DOCUMENTATION = {
  summary: "Require Zod validation (`Schema.parse(...)` / `Schema.safeParse(...)`) when reading values out of a `FormData` object.",
  rationale: "FormData values are untrusted strings or files and need runtime validation before use.",
  remediation: "Read the value inside a Zod schema's `parse` or `safeParse` input.",
  category: "security",
  limitations: [
    "Tests are excluded; imported schema-shaped names are trusted when their implementation is outside the linted file.",
    "Delayed raw-value use is accepted only after an unconditional successful parse in the same block; safeParse remains valid when the raw binding has no unvalidated consumer.",
    "An enclosing parse does not validate an earlier call or deferred callback that consumes its input. Direct object/array construction, unshadowed Object.fromEntries and native Number/String/Boolean coercion remain supported; arbitrary preprocessing needs an explicitly reviewed boundary.",
  ],
  examples: [
    { id: "validated-form-value", title: "Validate the form value", outcome: "no-match", files: [{ path: "src/action.ts", source: "const input = UserSchema.parse({ name: formData.get('name') });" }], focusPath: "src/action.ts", expectedCount: 0, public: true },
    { id: "raw-form-value", title: "Do not use a raw form value", outcome: "match", files: [{ path: "src/action.ts", source: "const name = formData.get('name');" }], focusPath: "src/action.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
