/** @fileoverview duplicate-test-body — the documentation and executable examples of `@sarj/duplicate-test-body`. */

import type { RuleDocumentation } from "../documentation.js";

export const DUPLICATE_TEST_BODY_DOCUMENTATION = {
  summary:
    "Disallow substantial sibling tests with the same body shape; express their differing inputs as a parameterized case table.",
  rationale:
    "Copy-pasted test bodies hide the cases that differ and allow equivalent assertions to drift independently.",
  remediation:
    "Consider a case table with one named test or subtest per case; preserve setup lifetime, test modifiers, and each case's assertions rather than deleting coverage.",
  category: "testing",
  limitations: [
    "The rule compares substantial sibling tests within one suite and skips inline snapshots and materially different comments. Short no-substitution strings and const-asserted literals share the existing input normalization; assertion values, property names, multiline strings and long strings retain their contracts.",
    "Matching normalized body shapes do not prove runtime equivalence or independent setup; parameterization is a manual review, not an automatic deletion.",
  ],
  examples: [
    {
      id: "parameterized-cases",
      title: "A case table shares one test body",
      outcome: "no-match",
      files: [{
        path: "src/user.test.ts",
        source: "test.each(['a', 'b'])('accepts %s', (value) => { const result = parse(value); expect(result.ok).toBe(true); expect(result.value).toBe(value); });",
      }],
      focusPath: "src/user.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "copied-sibling-tests",
      title: "Sibling tests repeat the same body",
      outcome: "match",
      files: [{
        path: "src/user.test.ts",
        source: "test('accepts a', () => { const value = 'a'; const result = parse(value); expect(result.ok).toBe(true); expect(result.value).toBe(value); });\ntest('accepts b', () => { const value = 'b'; const result = parse(value); expect(result.ok).toBe(true); expect(result.value).toBe(value); });",
      }],
      focusPath: "src/user.test.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
