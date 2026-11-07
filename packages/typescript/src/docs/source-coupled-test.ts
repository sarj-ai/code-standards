/** @fileoverview source-coupled-test — the documentation and executable examples of `@sarj/source-coupled-test`. */

import type { RuleDocumentation } from "../documentation.js";

export const SOURCE_COUPLED_TEST_DOCUMENTATION = {
  summary: "Disallow raw repository source text as a test oracle; parse or execute the artifact instead.",
  rationale: "Substring and regex checks can pass on comments or unreachable configuration and fail after behavior-preserving formatting changes.",
  remediation: "Reuse adequate existing validation; otherwise assert a distinct parsed or runtime contract. Preserve deliberate representation contracts with an exact justified suppression.",
  category: "testing",
  limitations: [
    "The rule follows stable lexical bindings, static source paths including JSX/TSX, CSS and HTML, awaited reads, and common text operations. Named imports of node:path/path join and resolve are followed when their complete trailing static path proves a source suffix. Reassigned bindings, dynamic trailing segments, namespace path wrappers, unknown path wrappers, iterator pipelines, and interprocedural flows remain unreported.",
    "Assertion roots are scope-resolved for supported test runners and Node assert imports; local or unknown helpers with assertion-like names are not inferred.",
    "Known fixture, golden, snapshot, and generated source paths are representation contracts and remain unreported; dot segments in the known path are normalized first.",
    "Contained static paths, including stable nested join/resolve descendants, beneath a native mkdtemp/mkdtempSync result are generated artifacts. Absolute or drive-anchored resolve segments and traversal above the proven directory remain unproven. Literal replace/replaceAll nonidentity guards comparing the same raw read remain unreported; fixed-string comparisons remain candidates.",
    "When raw representation is genuinely the contract (for example a golden or compatibility sentinel), use an exact line suppression with the reason.",
  ],
  examples: [
    {
      id: "parsed-policy-contract",
      title: "Assert on parsed policy behavior",
      outcome: "no-match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const policy = JSON.parse(readFileSync('policy.json', 'utf8')); expect(validate(policy)).toEqual([]); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "workflow-substring-contract",
      title: "Do not prove workflow behavior with a regex",
      outcome: "match",
      files: [{ path: "src/policy.test.ts", source: "import { readFileSync } from 'node:fs'; test('policy', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toMatch(/permissions/); });" }],
      focusPath: "src/policy.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
