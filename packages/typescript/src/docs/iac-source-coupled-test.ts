/** @fileoverview iac-source-coupled-test — the documentation and executable examples of `@sarj/iac-source-coupled-test`. */

import type { RuleDocumentation } from "../documentation.js";

export const IAC_SOURCE_COUPLED_TEST_DOCUMENTATION = {
  summary: "Disallow raw IaC source text as a test oracle; inspect a rendered plan, provider state, or runtime behavior.",
  rationale: "Substring and regex checks can pass on comments, formatting, or unreachable Terraform configuration while clients fail silently.",
  remediation: "Reuse adequate existing validation; otherwise assert a distinct rendered-plan, provider-state, or runtime contract. Preserve deliberate representation contracts with an exact justified suppression.",
  category: "testing",
  limitations: [
    "The rule follows stable lexical bindings and static source paths, including named node:path/path join and resolve imports with a complete trailing static path. Reassigned bindings, dynamic trailing paths, namespace or unknown path wrappers, iterator pipelines, and interprocedural flows remain unreported.",
    "Known fixture, golden, snapshot, and generated source paths remain unreported after dot-segment normalization, as do contained static paths beneath stable native temporary directories and literal mutation nonidentity guards comparing the same read.",
    "When raw representation is genuinely the contract, use an exact line suppression explaining that contract.",
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
