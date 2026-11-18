import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/no-unsignaled-poll.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

const TEST_FILE = "/repo/src/save.test.ts";
const SOURCE_FILE = "/repo/src/save.ts";
const IMPORTS = "import { expect, it, vi } from 'vitest';";

const valid = (name: string, code: string, filename = TEST_FILE) => ({ name, code: `${IMPORTS} ${code}`, filename });
const invalid = (name: string, code: string, count = 1) => ({
  name, code: `${IMPORTS} ${code}`, filename: TEST_FILE, errors: Array.from({ length: count }, () => ({ messageId: "noUnsignaledPoll" })),
});

ruleTester().run("no-unsignaled-poll", rule, {
  valid: [
    valid("awaits a signal", "it('saves', async () => { await called.promise; expect(save).toHaveBeenCalledOnce(); });"),
    valid("polls application state", "it('saves', async () => { await vi.waitFor(() => expect(status()).toBe('saved')); });"),
    valid("polls rendered state", "it('saves', async () => { await expect.poll(() => screen.getByText('Saved')).toBeTruthy(); });"),
    valid("spy assertion in a nested function", "it('saves', async () => { await vi.waitFor(() => { const later = () => expect(save).toHaveBeenCalled(); return status(); }); });"),
    valid("callback passed by reference", "it('saves', async () => { await vi.waitFor(check); });"),
    valid("non-framework expect", "it('saves', async () => { const assertion = { poll: (fn: () => unknown) => fn }; await vi.waitFor(() => assertion.poll(() => save.mock.calls)); });"),
    valid("local vi", "it('saves', async () => { const vi = { waitFor: (fn: () => unknown) => fn() }; await vi.waitFor(() => expect(save).toHaveBeenCalled()); });"),
    valid("non-test file", "await vi.waitFor(() => expect(save).toHaveBeenCalled());", SOURCE_FILE),
    valid("mock property on application object", "it('saves', async () => { await vi.waitFor(() => expect(server.mock).toBeDefined()); });"),
  ],
  invalid: [
    invalid("waitFor on spy", "it('saves', async () => { await vi.waitFor(() => expect(save).toHaveBeenCalledOnce()); });"),
    invalid("waitFor block body", "it('saves', async () => { await vi.waitFor(() => { expect(save).toHaveBeenCalledWith('a'); }); });"),
    invalid("negated poll passes vacuously", "it('saves', async () => { await vi.waitFor(() => expect(save).not.toHaveBeenCalled()); });"),
    invalid("several spy assertions report the poll once", "it('saves', async () => { await vi.waitFor(() => { expect(a).toHaveBeenCalled(); expect(b).toHaveBeenCalled(); }); });"),
    invalid("expect.soft", "it('saves', async () => { await vi.waitFor(() => expect.soft(save).toHaveBeenCalled()); });"),
    invalid("waitUntil on mock calls", "it('saves', async () => { await vi.waitUntil(() => save.mock.calls.length > 0); });"),
    invalid("expect.poll on mock calls", "it('saves', async () => { await expect.poll(() => save.mock.calls.length).toBe(1); });"),
    invalid("expect.poll chained spy matcher", "it('saves', async () => { await expect.poll(() => save).toHaveBeenCalled(); });"),
  ],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["no-unsignaled-poll"])).resolves.toBeGreaterThan(0);
});
