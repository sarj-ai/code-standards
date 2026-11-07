/** @fileoverview no-duplicate-test-case — the documentation and executable examples of `@sarj/no-duplicate-test-case`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DUPLICATE_TEST_CASE_DOCUMENTATION = {
  defaultLevel: "error",
  summary: "Report repeated literal rows in framework each tables and Vitest for tables.",
  rationale: "Identical rows repeat the same inputs and expected values without exposing a distinct case. Accidental duplicates consume test time and hide a missing boundary vector.",
  remediation: "Remove the accidental duplicate or replace it with the intended distinct boundary. Preserve intentional repeated or stateful scenarios with a local explanation; do not delete their coverage automatically.",
  category: "testing",
  limitations: [
    "Only literal rows in inline arrays or const tables used exclusively by each or Vitest for calls are compared. Calls, spreads, computed keys, getters, runtime values, tagged tables and mutable or escaped tables are excluded.",
    "Object property order and all row fields, including names and IDs, remain part of case identity; equivalent quoted and unquoted property names share one identity. Runtime imports and unchanged local const Vitest test.extend fixture APIs are resolved; type-only imports, escaped or mutated fixture APIs, custom runners and namespace imports are excluded.",
    "The rule reports duplicate values, not runtime equivalence. There is no autofix because repeated invocations may exercise shared state or concurrency.",
  ],
  examples: [
    {id: "duplicate-row", title: "A copied row misses the intended boundary", outcome: "match", files: [{path: "src/format.test.ts", source: "import {it} from 'vitest'; it.each([[0, '0ms'], [0, '0ms']])('%s', (input, expected) => { expect(format(input)).toBe(expected); });"}], focusPath: "src/format.test.ts", expectedCount: 1, public: true},
    {id: "distinct-boundary", title: "Distinct inputs have independent rows", outcome: "no-match", files: [{path: "src/format.test.ts", source: "import {it} from 'vitest'; it.each([[0, '0ms'], [1, '1ms']])('%s', (input, expected) => { expect(format(input)).toBe(expected); });"}], focusPath: "src/format.test.ts", expectedCount: 0, public: true},
    {id: "duplicate-for-row", scenarioId: "for-table", title: "Vitest for tables retain the same case identity", outcome: "match", files: [{path: "src/format.test.ts", source: "import {test} from 'vitest'; test.for([{input: 0, expected: '0ms'}, {'input': 0, expected: '0ms'}])('$input', ({input, expected}) => { expect(format(input)).toBe(expected); });"}], focusPath: "src/format.test.ts", expectedCount: 1, public: true},
    {id: "distinct-for-boundary", scenarioId: "for-table", title: "Vitest for tables preserve distinct boundaries", outcome: "no-match", files: [{path: "src/format.test.ts", source: "import {test} from 'vitest'; test.for([{input: 0, expected: '0ms'}, {'input': 1, expected: '1ms'}])('$input', ({input, expected}) => { expect(format(input)).toBe(expected); });"}], focusPath: "src/format.test.ts", expectedCount: 0, public: true},
    {id: "fixture-duplicate-row", scenarioId: "fixture-runner", title: "Fixture reuse preserves the literal case check", outcome: "match", files: [{path: "src/format.test.ts", source: "import {test as base} from 'vitest'; const test = base.extend({locale: 'en'}); test.for([1, 1])('formats %s', (value, {locale}) => { expect(format(value, locale)).toBe('1'); });"}], focusPath: "src/format.test.ts", expectedCount: 1, public: true},
    {id: "fixture-distinct-row", scenarioId: "fixture-runner", title: "Fixture reuse preserves distinct independent cases", outcome: "no-match", files: [{path: "src/format.test.ts", source: "import {test as base} from 'vitest'; const test = base.extend({locale: 'en'}); test.for([1, 2])('formats %s', (value, {locale}) => { expect(format(value, locale)).toBe(String(value)); });"}], focusPath: "src/format.test.ts", expectedCount: 0, public: true},
  ],
} as const satisfies RuleDocumentation;
