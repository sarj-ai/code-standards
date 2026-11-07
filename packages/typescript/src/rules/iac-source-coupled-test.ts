/**
 * @fileoverview iac-source-coupled-test — IaC source text is not a behavioral test oracle.
 *
 * Port of the 18.x `iac-source-coupled-test` rule; the algorithm lives in `_create-source-coupled-rule.ts`.
 */

import { createSourceCoupledRule } from "./_create-source-coupled-rule.js";

const IAC_SOURCE_SUFFIX_RE = /(?:\.tf\.json|\.tftest\.(?:hcl|json)|\.(?:hcl|tf|tfvars))$/iu;

export default createSourceCoupledRule(
  "iac-source-coupled-test",
  "Disallow raw IaC source text as a test oracle; inspect a rendered plan, provider state, or runtime behavior.",
  IAC_SOURCE_SUFFIX_RE,
);
