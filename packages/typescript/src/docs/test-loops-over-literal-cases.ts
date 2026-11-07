/** @fileoverview test-loops-over-literal-cases — the documentation and executable examples of `@sarj/test-loops-over-literal-cases`. */

import type { RuleDocumentation } from "../documentation.js";

export const TEST_LOOPS_OVER_LITERAL_CASES_DOCUMENTATION = {
  summary: "Disallow assertions over an inline literal case loop in a test; parameterization reports and names every case independently.",
  rationale: "A loop is reported as one test, so failures hide the individual case name and may stop later cases from running.",
  remediation: "Create one named parameterized test or runner-aware subtest for each literal case.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**"],
  limitations: ["Only inline literal for-of cases containing framework assertions are reported. References to setup or parameters owned by the enclosing test, and loops followed by statements in the same or enclosing block, are excluded because they can belong to an ordered scenario. External helper purity is not inferred."],
  examples: [
    { id: "parameterized-cases", title: "Use a parameterized test", outcome: "no-match", files: [{ path: "src/parser.test.ts", source: "test.each(['a', 'b'])('parses %s', (value) => { expect(parse(value)).toBe(value); });" }], focusPath: "src/parser.test.ts", expectedCount: 0, public: true },
    { id: "looped-cases", title: "Do not hide cases in a loop", outcome: "match", files: [{ path: "src/parser.test.ts", source: "test('parses', () => { for (const value of ['a', 'b']) { expect(parse(value)).toBe(value); } });" }], focusPath: "src/parser.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
