/**
 * @fileoverview source-coupled-test — raw repository source text is not a behavioral oracle.
 *
 * Port of the 18.x `source-coupled-test` rule; the algorithm lives in `_create-source-coupled-rule.ts`.
 */

import { createSourceCoupledRule } from "./_create-source-coupled-rule.js";

// Terraform JSON has a dedicated oracle owner; JSONC remains general source.
const GENERAL_SOURCE_SUFFIX_RE = /\.(?:bash|sh|ya?ml|jsonc|toml|py|css|html|[cm]?[jt]s|[jt]sx)$|(?<!\.(?:tf|tftest))\.json$/iu;

export default createSourceCoupledRule(
  "source-coupled-test",
  "Disallow raw repository source text as a test oracle; parse or execute the artifact instead.",
  GENERAL_SOURCE_SUFFIX_RE,
);
