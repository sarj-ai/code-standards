/** @fileoverview prefer-test-fixture-reuse — the documentation and executable examples of `@sarj/prefer-test-fixture-reuse`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_TEST_FIXTURE_REUSE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Reuse a requested test fixture instead of constructing another instance of its class.",
  rationale: "A second constructor bypasses the fixture's overrides, caching, configuration and cleanup ownership.",
  remediation: "Use the requested fixture. Supply a typed factory fixture when a test requires different configuration or multiple independent instances.",
  category: "testing",
  autofix: "none",
  limitations: [
    "Follows unchanged local const Vitest/Playwright test.extend APIs with literal fixture objects. A fixture must supply a source-resolved new-expression directly or through one local const to its use callback. Direct value fixtures are supported.",
    "Only constructors directly in a requesting test callback are compared by lexical binding identity. Renamed fixture parameters and stable constructor aliases are supported; nested callbacks, imported fixture APIs, dynamic factories, spread fixtures, mutable APIs and table-driven tests are excluded.",
    "Reports variants for review without replacing constructor arguments or changing lifecycle. Interface substitution across different concrete constructors requires typed project analysis and is not inferred.",
  ],
  examples: [
    { id: "duplicate-store", title: "The test constructs the store its fixture supplied", outcome: "match", files: [{ path: "src/store.test.ts", source: "import {test as base} from 'vitest'; class Store {} const test = base.extend({store: async ({}, use) => { await use(new Store()); }}); test('reads', ({store}) => { const other = new Store(); expect(other).toBeDefined(); });" }], focusPath: "src/store.test.ts", expectedCount: 1, public: true },
    { id: "reuse-store", title: "Request and use the store fixture", outcome: "no-match", files: [{ path: "src/store.test.ts", source: "import {test as base} from 'vitest'; class Store {} const test = base.extend({store: async ({}, use) => { await use(new Store()); }}); test('reads', ({store}) => { expect(store).toBeDefined(); });" }], focusPath: "src/store.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
