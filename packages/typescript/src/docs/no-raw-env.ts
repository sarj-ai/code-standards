/** @fileoverview no-raw-env — the documentation and executable examples of `@sarj/no-raw-env`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_RAW_ENV_DOCUMENTATION = {
  summary: "Disallow direct `process.env` and `import.meta.env` reads outside validated boundaries.",
  rationale: "Raw environment reads are untyped and defer invalid configuration failures until use.",
  remediation: "Validate environment values at startup and import the typed configuration object.",
  category: "correctness",
  limitations: ["Host markers, assignment targets, tests, scripts, build config, and recognized validation-boundary files are policy exemptions. A validation call does not prove every export is validated; assignment-target exemptions also include compound writes that read the previous value."],
  examples: [
    { id: "validated-environment", title: "Read validated configuration", outcome: "no-match", files: [{ path: "src/database.ts", source: "import { env } from './env.js'; const url = env.DATABASE_URL;" }], focusPath: "src/database.ts", expectedCount: 0, public: true },
    { id: "raw-environment-read", title: "Do not read raw configuration", outcome: "match", files: [{ path: "src/database.ts", source: "const url = process.env.DATABASE_URL;" }], focusPath: "src/database.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
