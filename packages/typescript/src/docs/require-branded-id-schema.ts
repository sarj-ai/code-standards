/** @fileoverview Documentation and executable examples for require-branded-id-schema. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_BRANDED_ID_SCHEMA_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Brand Zod identifier schemas so validated identifiers retain their domain.",
  rationale:
    "Validating the format of a scenario ID or session ID still produces a plain string. Distinct brands let TypeScript catch swaps between roles that use the same primitive representation.",
  remediation:
    "Apply a distinct Zod brand to each identifier domain at its parse boundary. Derive the TypeScript ID type with z.output or z.infer, and reuse its schema in objects that carry the ID.",
  category: "correctness",
  autofix: "none",
  limitations: [
    "Scalar chains and object factories must resolve to direct value imports from zod or zod/v4. Generated files and opaque chains are skipped.",
    "Object checks use direct ID fields whose values are visible in the literal. A schema reference named *IdSchema counts as a brand signal by convention.",
    "Role names can describe the same domain, such as sourceId and targetId. Wire contracts may need to keep primitive types until they are parsed into application types.",
  ],
  examples: [
    {
      id: "recording-ids-without-brands",
      title: "A take and a session validate as the same type",
      outcome: "match",
      files: [{ path: "src/recording.ts", source: "import { z } from 'zod';\nexport const RecordingSchema = z.strictObject({ takeId: z.uuid(), sessionId: z.uuid() });" }],
      focusPath: "src/recording.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "recording-ids-with-brands",
      title: "Brand each parsed identifier with its own domain",
      outcome: "no-match",
      files: [{ path: "src/recording.ts", source: "import { z } from 'zod';\nconst TakeIdSchema = z.uuid().brand<'TakeId'>();\nconst SessionIdSchema = z.uuid().brand<'SessionId'>();\nexport const RecordingSchema = z.strictObject({ takeId: TakeIdSchema, sessionId: SessionIdSchema });" }],
      focusPath: "src/recording.ts",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
