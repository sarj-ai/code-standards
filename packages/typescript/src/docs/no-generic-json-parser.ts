/** @fileoverview no-generic-json-parser — the documentation and executable examples of `@sarj/no-generic-json-parser`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_GENERIC_JSON_PARSER_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Parse known JSON fields with an object schema instead of an open JSON or record parser.",
  rationale: "An open JSON parser checks serialization or value kinds without declaring required fields, leaving application reads outside the validation contract.",
  remediation: "Define a focused z.object schema for the fields being read and infer its output type. Keep generic JSON at deliberate opaque forwarding or storage boundaries.",
  category: "correctness",
  requiresTypeInformation: false,
  runtimeImports: ["zod"],
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-unsafe-dictionary-type.ts"],
  limitations: [
    "Checks static property reads on direct or stable-const aliases of Zod parse/parseAsync outputs and proven successful safeParse/awaited safeParseAsync data from json, any, unknown, record and partialRecord schemas. Resolves runtime Zod imports, local const schema aliases and identity-preserving schema wrappers.",
    "Dynamic dictionary indexing, opaque JSON forwarding/storage, imported schemas, recursive lazy definitions, custom validator implementations, mutable aliases, unproven success guards and transformation/refinement callbacks are excluded. Subsequent parser validation with a specific or unresolved contract and meaningful typed/finite-key records are preserved. Generated/vendor files are excluded; maintained tests are checked.",
    "The rule identifies a missing declared field contract; it does not infer all external payload fields or automatically change runtime validation.",
  ],
  examples: [
    { id: "open-record-read", title: "Generic validation does not declare the field", outcome: "match", files: [{ path: "src/request.ts", source: "import { z } from 'zod'; const JsonSchema = z.record(z.string(), z.unknown()); function load(raw: unknown) { const body = JsonSchema.parse(raw); return body.version; }" }], focusPath: "src/request.ts", expectedCount: 1, public: true },
    { id: "focused-record-read", title: "Declare only the fields being read", outcome: "no-match", files: [{ path: "src/request.ts", source: "import { z } from 'zod'; const VersionSchema = z.object({ version: z.number().int().positive() }); function load(raw: unknown) { return VersionSchema.parse(raw).version; }" }], focusPath: "src/request.ts", expectedCount: 0, public: true },
    {"id": "safe-parse-fields-before", "scenarioId": "safe-parse-fields", "title": "Validate the fields consumed after success — before", "outcome": "match", "files": [{"path": "src/example.ts", "source": "import { z } from 'zod'; function load(raw: unknown) { const result = z.record(z.string(), z.unknown()).safeParse(raw); if (!result.success) return; return result.data.id; }"}], "focusPath": "src/example.ts", "expectedCount": 1, "public": true},
    {"id": "safe-parse-fields-after", "scenarioId": "safe-parse-fields", "title": "Validate the fields consumed after success — after", "outcome": "no-match", "files": [{"path": "src/example.ts", "source": "import { z } from 'zod'; function load(raw: unknown) { const result = z.object({ id: z.string() }).safeParse(raw); if (!result.success) return; return result.data.id; }"}], "focusPath": "src/example.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;
