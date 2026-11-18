import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/no-flake-masking.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

const TEST_FILE = "/repo/src/sync.test.ts";
const SOURCE_FILE = "/repo/src/sync.ts";
const CONFIG_FILE = "/repo/vitest.config.ts";
const PLAYWRIGHT_CONFIG = "/repo/tests/e2e/playwright.config.ts";
const PLAYWRIGHT_TEST = "/repo/tests/e2e/login.spec.ts";

const valid = (name: string, code: string, filename = TEST_FILE) => ({ name, code, filename });
const invalid = (name: string, code: string, messageId: "retry" | "timeout", filename = TEST_FILE, count = 1) => ({
  name, code, filename, errors: Array.from({ length: count }, () => ({ messageId })),
});

ruleTester().run("no-flake-masking", rule, {
  valid: [
    valid("plain test", "import { it } from 'vitest'; it('syncs', async () => { await sync(); });"),
    valid("zero retry", "import { it } from 'vitest'; it('syncs', { retry: 0 }, async () => {});"),
    valid("false retry const", "import { it } from 'vitest'; const RETRY = 0; it('syncs', { retry: RETRY }, async () => {});"),
    valid("default timeout", "import { it } from 'vitest'; it('syncs', async () => {}, 5000);"),
    valid("lowered timeout option", "import { it } from 'vitest'; it('syncs', { timeout: 200 }, async () => {});"),
    valid("unresolved timeout stays opaque", "import { it } from 'vitest'; it('syncs', async () => {}, budget());"),
    valid("hook timeout is outside per-test policy", "import { beforeAll } from 'vitest'; beforeAll(async () => { await boot(); }, 60_000);"),
    valid("local test helper", "function it(name: string, fn: () => void, timeout: number) { return [name, fn, timeout]; } it('x', () => {}, 60_000);"),
    valid("unrelated test import", "import { it } from './harness.js'; it('x', () => {}, 60_000);"),
    valid("non-test file test call", "it('x', () => {}, 60_000);", SOURCE_FILE),
    valid("playwright test details are not unit options", "import { test } from '@playwright/test'; test('logs in', { tag: '@smoke' }, async () => {});", PLAYWRIGHT_TEST),
    valid("playwright default timeout", "import { test } from '@playwright/test'; test.setTimeout(30_000);", PLAYWRIGHT_TEST),
    valid("vitest config without retry", "import { defineConfig } from 'vitest/config'; export default defineConfig({ test: { testTimeout: 20_000 } });", CONFIG_FILE),
    valid("unrelated defineConfig", "import { defineConfig } from 'vite'; export default defineConfig({ test: { retry: 2 } });", CONFIG_FILE),
    valid("playwright zero retries", "import { defineConfig } from '@playwright/test'; export default defineConfig({ retries: 0, timeout: 90_000 });", PLAYWRIGHT_CONFIG),
    valid("vi.setConfig lowered timeout", "import { vi } from 'vitest'; vi.setConfig({ testTimeout: 1000 });"),
    valid("local vi object", "const vi = { setConfig(options: object) { return options; } }; vi.setConfig({ testTimeout: 60_000 });"),
  ],
  invalid: [
    invalid("retry option", "import { it } from 'vitest'; it('syncs', { retry: 2 }, async () => {});", "retry"),
    invalid("CI-conditional retry", "import { it } from 'vitest'; it('syncs', { retry: process.env.CI ? 2 : 0 }, async () => {});", "retry"),
    { name: "trailing retry and timeout options", filename: TEST_FILE, code: "import { test } from 'vitest'; test('syncs', async () => {}, { retry: 1, timeout: 20_000 });", errors: [{ messageId: "retry" }, { messageId: "timeout" }] },
    invalid("suite retry", "import { describe } from 'vitest'; describe('sync', { retry: 3 }, () => {});", "retry"),
    invalid("raised trailing timeout", "import { it } from 'vitest'; it('syncs', async () => {}, 30_000);", "timeout"),
    invalid("raised timeout through const", "import { it } from 'vitest'; const SLOW = 15_000; it('syncs', async () => {}, SLOW);", "timeout"),
    invalid("raised timeout option", "import { it } from 'vitest'; it('syncs', { timeout: 30_000 }, async () => {});", "timeout"),
    invalid("global test with modifier", "it.concurrent('syncs', async () => {}, 10_000);", "timeout"),
    invalid("each table", "import { it } from 'vitest'; it.each([1, 2])('syncs %i', async () => {}, 10_000);", "timeout"),
    invalid("vitest fixture test", "import { test as base } from 'vitest'; const test = base.extend({ port: 3000 }); test('syncs', async () => {}, 10_000);", "timeout"),
    invalid("vi.setConfig retry", "import { vi } from 'vitest'; vi.setConfig({ retry: 1 });", "retry"),
    invalid("vi.setConfig hook timeout", "vi.setConfig({ hookTimeout: 30_000 });", "timeout"),
    invalid("jest retryTimes", "import { jest } from '@jest/globals'; jest.retryTimes(3);", "retry"),
    invalid("jest setTimeout", "jest.setTimeout(20_000);", "timeout"),
    invalid("playwright setTimeout", "import { test } from '@playwright/test'; test.setTimeout(120_000);", "timeout", PLAYWRIGHT_TEST),
    invalid("playwright describe retries", "import { test } from '@playwright/test'; test.describe.configure({ retries: 2 });", "retry", PLAYWRIGHT_TEST),
    invalid("vitest config retry", "import { defineConfig } from 'vitest/config'; export default defineConfig({ test: { retry: 2 } });", "retry", CONFIG_FILE),
    invalid("vitest nested project retry", "import { defineConfig } from 'vitest/config'; export default defineConfig({ test: { projects: [{ test: { name: 'node', retry: 1 } }] } });", "retry", CONFIG_FILE),
    invalid("playwright config retries", "import { defineConfig } from '@playwright/test'; export default defineConfig({ retries: process.env.CI ? 2 : 0 });", "retry", PLAYWRIGHT_CONFIG),
    invalid("playwright project retries", "import { defineConfig } from '@playwright/test'; export default defineConfig({ projects: [{ name: 'chromium', retries: 1 }] });", "retry", PLAYWRIGHT_CONFIG),
  ],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["no-flake-masking"])).resolves.toBeGreaterThan(0);
});
