/** @fileoverview no-tautological-expect — the documentation and executable examples of `@sarj/no-tautological-expect`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION = {
  summary:
    "Disallow supported assertions fixed by literal setup or immutable self identity.",
  rationale:
    "An assertion fixed by literal setup or one immutable binding's identity cannot distinguish a wrong result from the intended behavior.",
  remediation: "Assert on a value produced by the behavior under test against an independently specified expectation, or remove only the redundant assertion while preserving coverage.",
  category: "testing",
  limitations: [
    "Only supported `expect` matcher calls in recognized test files are inspected, including imported aliases, static string messages on imported Vitest/Playwright expect calls, and a single `.not` on zero-argument matchers. Local or type-only bindings, regular expressions, async modifiers and unsupported coercions are excluded; failing constant assertions are not tautologies.",
    "The literal proof resolves scalar const bindings and aliases through lexical scope; mutable bindings, objects, arrays, destructuring, runtime initializers and forward references are excluded from that proof.",
    "Positive toBe assertions on the same initialized, unreassigned local identifier const binding also have fixed identity, including runtime results. Different bindings, imported live values, property/getter accesses and deep-equality reflexivity remain excluded from this identity proof.",
    "Expected-side runtime dependence, including a complete inline snapshot computed from its actual value, remains manual review; independent static interpolation and intentional partial masking are valid.",
    "Direct framework expect.extend registrations exclude replaced built-in matchers; opaque registrations exclude all supported matchers, and nonempty custom equality testers exclude deep equality. Direct synchronous expect callbacks observed by a throwing matcher retain their assertion contracts. Cross-file or indirect matcher customization is not inferred.",
  ],
  examples: [
    {
      id: "produced-value",
      title: "Assert on a produced value",
      outcome: "no-match",
      files: [{ path: "src/add.test.ts", source: "it('adds', () => { expect(add(1, 1)).toBe(2); });" }],
      focusPath: "src/add.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "literal-only-assertion",
      title: "Do not compare identical literals",
      outcome: "match",
      files: [{ path: "src/add.test.ts", source: "it('works', () => { expect(true).toBe(true); });" }],
      focusPath: "src/add.test.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "setup-only-oracle",
      scenarioId: "setup-only",
      title: "A const setup assertion never observes the application",
      outcome: "match",
      files: [{path: "src/service.test.ts", source: "it('works', () => { const status = 'ok'; expect(status).toBe('ok'); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "negated-setup-oracle",
      scenarioId: "negated-setup",
      title: "Negating a fixed matcher still does not observe the application",
      outcome: "match",
      files: [{path: "src/service.test.ts", source: "import {expect as verify} from 'vitest'; it('works', () => { const ready = false; verify(ready).not.toBeTruthy(); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "negated-produced-oracle",
      scenarioId: "negated-setup",
      title: "A negated assertion can observe a runtime result",
      outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "import {expect as verify} from 'vitest'; it('works', () => { verify(serviceStatus()).not.toBeNull(); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "produced-scalar-oracle",
      scenarioId: "setup-only",
      title: "A runtime scalar result remains a valid observation",
      outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "it('works', () => { const status = serviceStatus(); expect(status).toBe('ok'); });"}],
      focusPath: "src/service.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "message-only-oracle", scenarioId: "static-message", title: "A diagnostic string does not make a literal comparison observe behavior", outcome: "match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; expect(true, 'service ready').toBe(true);"}], focusPath: "src/service.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "message-produced-oracle", scenarioId: "static-message", title: "A diagnostic message can describe an observed result", outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; expect(serviceReady(), 'service ready').toBe(true);"}], focusPath: "src/service.test.ts", expectedCount: 0, public: true,
    },
    {
      id: "uncaptured-matcher", scenarioId: "matcher-contract", title: "An uncaptured literal assertion remains redundant", outcome: "match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect(true).toBeTruthy();"}], focusPath: "src/assertion.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "captured-matcher", scenarioId: "matcher-contract", title: "A throwing matcher observes the inner assertion contract", outcome: "no-match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect(() => expect(true).toBeTruthy()).not.toThrow();"}], focusPath: "src/assertion.test.ts", expectedCount: 0, public: true,
    },
    {
      id: "unrelated-custom-matcher", scenarioId: "custom-matcher", title: "Adding a different matcher preserves the built-in proof", outcome: "match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect.extend({toBeReady: custom}); expect(true).toBe(true);"}], focusPath: "src/assertion.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "replaced-custom-matcher", scenarioId: "custom-matcher", title: "A replaced matcher can reject a literal comparison", outcome: "no-match",
      files: [{path: "src/assertion.test.ts", source: "import {expect} from 'vitest'; expect.extend({toBe: () => ({pass: false, message: () => 'custom contract'})}); expect(true).toBe(true);"}], focusPath: "src/assertion.test.ts", expectedCount: 0, public: true,
    },
    {
      id: "self-identity-oracle", scenarioId: "immutable-identity", title: "A returned value's identity with itself cannot reject a wrong result", outcome: "match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; const result = serviceStatus(); expect(result).toBe(result);"}], focusPath: "src/service.test.ts", expectedCount: 1, public: true,
    },
    {
      id: "independent-result-oracle", scenarioId: "immutable-identity", title: "An independent expected state can reject a wrong result", outcome: "no-match",
      files: [{path: "src/service.test.ts", source: "import {expect} from 'vitest'; const result = serviceStatus(); expect(result.status).toBe('ready');"}], focusPath: "src/service.test.ts", expectedCount: 0, public: true,
    },
  ],
} as const satisfies RuleDocumentation;
