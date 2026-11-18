/** @fileoverview no-flake-masking — the documentation and executable examples of `@sarj/no-flake-masking`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_FLAKE_MASKING_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Fix flaky tests at their cause instead of retrying them or raising their timeouts.",
  rationale: "A test that passes on rerun, or only within a raised time budget, keeps the race or slowness that made it fail; CI turns green while the defect stays.",
  remediation: "Await the operation or the event the test depends on, use controlled timers, or move slow shared setup into a beforeAll hook. Remove the retry or timeout option once the test is deterministic.",
  category: "testing",
  references: ["https://github.com/interfere-inc/landmines/blob/main/packages/landmines/src/rules/no-flake-masking.ts"],
  limitations: [
    "Test-file checks cover Vitest, Jest and Bun test and suite calls (including modifiers, each tables and unchanged Vitest test.extend fixtures): a nonzero retry option, and a timeout option or trailing timeout argument above the 5000 ms framework default. Playwright test files are checked for test.setTimeout and test.describe.configure above its 30000 ms default and nonzero retries.",
    "vi.setConfig retry, testTimeout and hookTimeout, jest.retryTimes and jest.setTimeout are checked on the framework's own namespace.",
    "Config checks follow defineConfig, defineProject and mergeConfig imported from vitest/config or @playwright/test in any file: Vitest test.retry, including nested projects, and Playwright top-level and per-project retries. Retry values that are not statically zero or false are reported, including CI-conditional values.",
    "Timeouts are compared only when they are numeric literals or earlier unchanged local constants. Config-level time budgets, hook timeouts, test.slow(), project-level timeout defaults and fixture APIs imported from other modules are not inspected.",
  ],
  examples: [
    { id: "await-signal", title: "Await the signal within the default budget", outcome: "no-match", files: [{ path: "src/sync.test.ts", source: "import { it } from 'vitest'; it('syncs', async () => { await sync.done; expect(sync.state).toBe('idle'); });" }], focusPath: "src/sync.test.ts", expectedCount: 0, public: true },
    { id: "retry-option", title: "Do not rerun a failing test", outcome: "match", files: [{ path: "src/sync.test.ts", source: "import { it } from 'vitest'; it('syncs', { retry: 2 }, async () => { await sync.done; expect(sync.state).toBe('idle'); });" }], focusPath: "src/sync.test.ts", expectedCount: 1, public: true },
    { id: "raised-timeout", scenarioId: "timeout", title: "Do not raise a test's time budget", outcome: "match", files: [{ path: "src/sync.test.ts", source: "import { it } from 'vitest'; it('syncs', async () => { await sync.done; }, 30_000);" }], focusPath: "src/sync.test.ts", expectedCount: 1, public: true },
    { id: "lowered-timeout", scenarioId: "timeout", title: "A budget below the default does not hide slowness", outcome: "no-match", files: [{ path: "src/sync.test.ts", source: "import { it } from 'vitest'; it('syncs', async () => { await sync.done; }, 1000);" }], focusPath: "src/sync.test.ts", expectedCount: 0, public: true },
    { id: "playwright-config-retries", scenarioId: "playwright-config", title: "Do not retry end-to-end suites in CI", outcome: "match", files: [{ path: "playwright.config.ts", source: "import { defineConfig } from '@playwright/test'; export default defineConfig({ retries: process.env.CI ? 2 : 0 });" }], focusPath: "playwright.config.ts", expectedCount: 1, public: true },
    { id: "playwright-config-no-retries", scenarioId: "playwright-config", title: "Run each end-to-end test once", outcome: "no-match", files: [{ path: "playwright.config.ts", source: "import { defineConfig } from '@playwright/test'; export default defineConfig({ retries: 0 });" }], focusPath: "playwright.config.ts", expectedCount: 0, public: true },
  ],
} as const satisfies RuleDocumentation;
