/** @fileoverview no-sleep-in-test-body — the documentation and executable examples of `@sarj/no-sleep-in-test-body`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SLEEP_IN_TEST_BODY_DOCUMENTATION = {
  summary: "Avoid fixed timed sleeps directly in test bodies; synchronize on observable behavior or use controlled timers.",
  rationale: "Wall-clock delays make test correctness depend on scheduler and machine speed.",
  remediation: "Await the observable signal, or advance fake timers when supported and restore real timers in finally or a teardown hook.",
  category: "testing",
  filePatterns: ["**/*.test.*", "**/*.spec.*", "**/tests/**", "**/__tests__/**"],
  limitations: ["Only fixed nonzero sleeps directly inside test and per-test hook callbacks are checked, including unchanged local const Vitest test.extend fixture APIs and their beforeEach/afterEach hooks. Escaped or mutated fixture APIs, nested fakes, parameterized delays, local helper bindings, and Promise executors with additional work or rejection callbacks are excluded."],
  examples: [
    { id: "fake-timer", title: "Advance controlled time and restore real timers", outcome: "no-match", files: [{ path: "src/retry.test.ts", source: "it('retries', async () => { vi.useFakeTimers(); try { const result = retry(); await vi.advanceTimersByTimeAsync(50); await result; } finally { vi.useRealTimers(); } });" }], focusPath: "src/retry.test.ts", expectedCount: 0, public: true },
    { id: "fixed-sleep", title: "Do not wait for wall-clock time", outcome: "match", files: [{ path: "src/retry.test.ts", source: "it('retries', async () => { await sleep(50); expect(done()).toBe(true); });" }], focusPath: "src/retry.test.ts", expectedCount: 1, public: true },
    { id: "fixture-fixed-sleep", scenarioId: "fixture-runner", title: "Fixture setup does not make a fixed sleep deterministic", outcome: "match", files: [{ path: "src/retry.test.ts", source: "import {test as base} from 'vitest'; const test = base.extend({port: 3000}); test('retries', async ({port}) => { start(port); await sleep(50); expect(done()).toBe(true); });" }], focusPath: "src/retry.test.ts", expectedCount: 1, public: true },
    { id: "fixture-observable-signal", scenarioId: "fixture-runner", title: "Await the signal while reusing fixture setup", outcome: "no-match", files: [{ path: "src/retry.test.ts", source: "import {test as base} from 'vitest'; const test = base.extend({port: 3000}); test('retries', async ({port}) => { start(port); await waitForReady(port); expect(done()).toBe(true); });" }], focusPath: "src/retry.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
