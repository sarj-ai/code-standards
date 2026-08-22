/**
 * @fileoverview iac-source-coupled-test — IaC source text is not a behavioral test oracle.
 *
 * Examples: https://github.com/sarj-ai/code-standards/blob/main/packages/typescript/tests/rules/iac-source-coupled-test.test.ts
 */

import { type RuleDocumentation } from "./_docs.js";
import { createSourceCoupledRule } from "./source-coupled-test.js";

const IAC_SOURCE_SUFFIX_RE = /(?:\.tf\.json|\.tftest\.(?:hcl|json)|\.(?:hcl|tf|tfvars))$/iu;

export const IAC_SOURCE_COUPLED_TEST_DOCUMENTATION = {
  summary: "Disallow raw IaC source text as a test oracle; inspect a rendered plan, provider state, or runtime behavior.",
  rationale: "Substring and regex checks can pass on comments, formatting, or unreachable Terraform configuration while clients fail silently.",
  remediation: "Parse rendered plan JSON, query the provider, or exercise the deployed runtime contract.",
  category: "testing",
  limitations: [
    "The rule follows lexical aliases, source-path collections, awaited reads, and common text operations; interprocedural flows remain unreported.",
    "The warning-stage rule remains suppressible for calibration; promotion may make the locked policy non-suppressible.",
  ],
  examples: [
    {
      id: "rendered-plan-contract",
      title: "Assert on rendered plan behavior",
      outcome: "no-match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const plan = JSON.parse(readFileSync('plan.json', 'utf8')); expect(validate(plan)).toEqual([]); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "terraform-substring-contract",
      title: "Do not prove Terraform behavior with a regex",
      outcome: "match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const source = readFileSync('main.tf', 'utf8'); expect(source).toMatch(/prevent_destroy/); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;

export default createSourceCoupledRule(
  "iac-source-coupled-test",
  IAC_SOURCE_COUPLED_TEST_DOCUMENTATION,
  IAC_SOURCE_SUFFIX_RE,
);
