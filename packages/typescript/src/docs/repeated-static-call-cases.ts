/** @fileoverview repeated-static-call-cases — the documentation and executable examples of `@sarj/repeated-static-call-cases`. */

import type { RuleDocumentation } from "../documentation.js";

export const REPEATED_STATIC_CALL_CASES_DOCUMENTATION = {
  summary: "Review three or more consecutive static-input call assertions as potential named cases.",
  rationale: "Copy-pasted cases obscure the input table, and a thrown assertion can stop later cases from being reported.",
  remediation: "If the calls are independent, use the runner's named parameterized cases or subtests. Preserve ordered state-transition scenarios as one test.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only consecutive top-level assertions with direct calls and static inputs and expected values are checked. Test-local callees and fixtures are excluded; imported or outer functions can still be stateful, so manual independence review is required. Not every runner supports test.each."],
  examples: [
    { id: "parameterized", title: "Name each case", outcome: "no-match", files: [{ path: "src/parser.test.ts", source: "test.each([['a', true], ['b', false], ['c', true]])('parses %s', (input, expected) => { expect(parse(input)).toBe(expected); });" }], focusPath: "src/parser.test.ts", expectedCount: 0, public: true },
    { id: "repeated", title: "Do not repeat literal cases", outcome: "match", files: [{ path: "src/parser.test.ts", source: "test('parses', () => { expect(parse('a')).toBe(true); expect(parse('b')).toBe(false); expect(parse('c')).toBe(true); });" }], focusPath: "src/parser.test.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
