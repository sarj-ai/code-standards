/** @fileoverview no-unsignaled-poll — the documentation and executable examples of `@sarj/no-unsignaled-poll`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNSIGNALED_POLL_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Await the event a test depends on instead of polling spy or mock state until a deadline.",
  rationale: "Polling a spy races the code under test against the poll deadline: under CI load the call lands after the deadline and the test fails, and a negated call assertion passes before the call can happen.",
  remediation: "Await the operation that makes the call, or have the test double resolve a promise when it is called and await that promise before asserting on the spy.",
  category: "testing",
  references: ["https://github.com/interfere-inc/landmines/blob/main/packages/landmines/src/rules/no-unsignaled-poll.ts"],
  limitations: [
    "Only vi.waitFor and vi.waitUntil on Vitest's namespace and expect.poll on a test framework's expect are checked, in test files.",
    "A poll is reported when its inline callback, outside nested functions, asserts a spy call or return matcher on expect or expect.soft, or reads mock.calls, mock.results, mock.lastCall or other mock state; expect.poll is also reported when a spy matcher is chained on it.",
    "Testing Library waitFor, callbacks passed by reference, polls on DOM or application state, and request recorders other than mock state are not inspected.",
  ],
  examples: [
    { id: "await-double-signal", title: "Await the promise the test double resolves", outcome: "no-match", files: [{ path: "src/save.test.ts", source: "import { expect, it, vi } from 'vitest'; it('saves', async () => { const called = Promise.withResolvers<void>(); const save = vi.fn(() => { called.resolve(); }); submit(save); await called.promise; expect(save).toHaveBeenCalledOnce(); });" }], focusPath: "src/save.test.ts", expectedCount: 0, public: true },
    { id: "poll-spy", title: "Do not poll a spy until a deadline", outcome: "match", files: [{ path: "src/save.test.ts", source: "import { expect, it, vi } from 'vitest'; it('saves', async () => { const save = vi.fn(); submit(save); await vi.waitFor(() => expect(save).toHaveBeenCalledOnce()); });" }], focusPath: "src/save.test.ts", expectedCount: 1, public: true },
    { id: "poll-mock-calls", scenarioId: "state-poll", title: "Do not poll recorded mock calls", outcome: "match", files: [{ path: "src/save.test.ts", source: "import { expect, it, vi } from 'vitest'; it('saves', async () => { const save = vi.fn(); submit(save); await expect.poll(() => save.mock.calls.length).toBe(1); });" }], focusPath: "src/save.test.ts", expectedCount: 1, public: true },
    { id: "poll-rendered-state", scenarioId: "state-poll", title: "Polling observable application state is outside this rule", outcome: "no-match", files: [{ path: "src/save.test.ts", source: "import { expect, it, vi } from 'vitest'; it('saves', async () => { submit(); await vi.waitFor(() => expect(status()).toBe('saved')); });" }], focusPath: "src/save.test.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
