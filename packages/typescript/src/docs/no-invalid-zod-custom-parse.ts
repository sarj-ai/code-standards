/** @fileoverview no-invalid-zod-custom-parse — the documentation and executable examples of `@sarj/no-invalid-zod-custom-parse`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION = {
  summary: "Do not parse an incompatible primitive literal through an unvalidated Zod custom schema.",
  rationale: "Without a validator, z.custom<T>() returns its input unchanged while promising T. A parsed primitive outside that value domain fabricates a contract the caller may trust.",
  remediation: "Provide actual validation, use the appropriate primitive schema, or retain an honest unknown result until validation. Preserve composed validators and independently owned domain contracts.",
  category: "correctness",
  defaultLevel: "error",
  autofix: "none",
  limitations: [
    "Requires type information and a direct inline z.custom<T>().parse(primitiveLiteral) call with no custom validator or parse options. Recognizes runtime imports from zod or zod/v4 and native installed Zod v4 declarations; schema bindings, compositions, safeParse, dynamic inputs and indirect calls are excluded.",
    "Targets must be broad primitives, finite unbranded primitive/nullish literal unions, or never. Any, unknown, void, object, enum, branded, intersection, generic and opaque targets are preserved. Membership is checked by primitive value, not nominal assignability. Null input requires strictNullChecks.",
    "The import binding must be used only by direct custom calls or type-only references. Other namespace uses, aliases, exports, mutation and escapes conservatively disable the proof for that binding. Generated files are excluded; tests remain checked. No autofix is offered.",
  ],
  references: ["https://zod.dev/api#custom"],
  examples: [
    { id: "validated-string", title: "Validate a primitive at the boundary", outcome: "no-match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const value = z.custom<string>(value => typeof value === "string").parse(1);' }], focusPath: "src/value.ts", expectedCount: 0, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
    { id: "fabricated-string", title: "An unchecked parser returns the number unchanged", outcome: "match", files: [{ path: "src/value.ts", source: 'import { z } from "zod"; const value = z.custom<string>().parse(1);' }], focusPath: "src/value.ts", expectedCount: 1, public: true, installedDependencies: [{ module: "zod", version: "4.6.7" }] },
  ],
} as const satisfies RuleDocumentation;
