import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import playwright from "../src/upstream/playwright.js";
import testingLibrary from "../src/upstream/testing-library.js";
import { ruleReports } from "./_native-rule";

const cases = [
  {
    plugin: playwright,
    rule: "missing-playwright-await",
    message: "missingAwait",
    invalid:
      "import { test } from '@playwright/test'; test('page', async ({ page }) => { page.waitForResponse('**/ready'); });",
    valid:
      "import { test } from '@playwright/test'; test('page', async ({ page }) => { await page.waitForResponse('**/ready'); });",
  },
  {
    plugin: playwright,
    rule: "no-unnecessary-assertions",
    message: "noUnnecessaryAssertions",
    invalid:
      "import { test, expect } from '@playwright/test'; test('page', async ({ page }) => { expect(page.locator('button')).toBeTruthy(); });",
    valid:
      "import { test, expect } from '@playwright/test'; test('page', async ({ page }) => { await expect(page.locator('button')).toBeVisible(); });",
  },
  {
    plugin: testingLibrary,
    rule: "await-async-events",
    message: "awaitAsyncEvent",
    invalid:
      "import userEvent from '@testing-library/user-event'; userEvent.click(button);",
    valid:
      "import userEvent from '@testing-library/user-event'; await userEvent.click(button);",
  },
  {
    plugin: testingLibrary,
    rule: "await-async-queries",
    message: "awaitAsyncQuery",
    invalid:
      "import { screen } from '@testing-library/react'; screen.findByText('Save');",
    valid:
      "import { screen } from '@testing-library/react'; await screen.findByText('Save');",
  },
  {
    plugin: testingLibrary,
    rule: "await-async-utils",
    message: "awaitAsyncUtil",
    invalid:
      "import { waitFor } from '@testing-library/react'; waitFor(() => expect(value).toBe(1));",
    valid:
      "import { waitFor } from '@testing-library/react'; await waitFor(() => expect(value).toBe(1));",
  },
  {
    plugin: testingLibrary,
    rule: "no-unnecessary-act",
    message: "noUnnecessaryActTestingLibraryUtil",
    invalid:
      "import { act, render } from '@testing-library/react'; act(() => { render(component); });",
    valid:
      "import { render } from '@testing-library/react'; render(component);",
  },
  {
    plugin: testingLibrary,
    rule: "prefer-screen-queries",
    message: "preferScreenQueries",
    invalid:
      "import { render } from '@testing-library/react'; const { getByText } = render(component); getByText('Save');",
    valid:
      "import { render, screen } from '@testing-library/react'; render(component); screen.getByText('Save');",
  },
];

for (const { plugin, rule, message, invalid, valid } of cases) {
  describe(rule, () => {
    it("reports the unchanged upstream violation in the native engine", () => {
      expect(
        ruleReports(plugin.rules[rule], invalid).map(
          (report) => report.messageId,
        ),
      ).toEqual([message]);
    });
    it("accepts the corresponding corrected source", () => {
      expect(ruleReports(plugin.rules[rule], valid)).toEqual([]);
    });
  });
}

it("preserves awaited imported aliases and local promise consumers", () => {
  const rule = testingLibrary.rules["await-async-queries"];
  expect(
    ruleReports(
      rule,
      "import { screen as view } from '@testing-library/react'; const result = view.findByText('Save'); await result;",
    ),
  ).toEqual([]);
});

it("preserves Playwright custom matcher options", () => {
  const rule = playwright.rules["missing-playwright-await"];
  const code =
    "import { expect } from '@playwright/test'; expect(value).toBeReady();";
  expect(
    ruleReports(rule, code, "/repo/page.spec.ts", [
      { customMatchers: ["toBeReady"] },
    ]).map((report) => report.messageId),
  ).toEqual(["missingAwait"]);
  expect(ruleReports(rule, code)).toEqual([]);
});

const packageDirectory = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const oxlintBinary = join(
  dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);

it("loads every retained rule in the actual stock CLI worker", () => {
  const root = mkdtempSync(join(tmpdir(), "native-framework-rules-"));
  try {
    for (const { plugin, rule, invalid, valid } of cases) {
      const family = plugin === playwright ? "playwright" : "testing-library";
      const alias = `sarj-${family}`;
      writeFileSync(
        join(root, ".oxlintrc.json"),
        JSON.stringify({
          categories: {
            correctness: "off",
            suspicious: "off",
            pedantic: "off",
            perf: "off",
            style: "off",
            restriction: "off",
            nursery: "off",
          },
          jsPlugins: [
            {
              name: alias,
              specifier: join(packageDirectory, `src/upstream/${family}.js`),
            },
          ],
          rules: { [`${alias}/${rule}`]: "error" },
        }),
      );
      for (const [code, expected] of [
        [invalid, 1],
        [valid, 0],
      ] as const) {
        writeFileSync(join(root, "probe.ts"), code);
        const result = spawnSync(
          process.execPath,
          [
            oxlintBinary,
            "--config",
            ".oxlintrc.json",
            "--format",
            "json",
            "probe.ts",
          ],
          {
            cwd: root,
            encoding: "utf8",
            timeout: 30_000,
          },
        );
        if (result.error) throw result.error;
        expect(result).toMatchObject({ status: expected, stderr: "" });
        const report = JSON.parse(result.stdout);
        expect(report["number_of_files"]).toBe(1);
        expect(
          report.diagnostics.filter(
            (diagnostic: { code?: string }) =>
              diagnostic.code === `${alias}(${rule})`,
          ),
        ).toHaveLength(expected);
      }
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

it("preserves an upstream async-query fix and reaches a stable second pass", () => {
  const root = mkdtempSync(join(tmpdir(), "native-framework-fix-"));
  try {
    writeFileSync(
      join(root, ".oxlintrc.json"),
      JSON.stringify({
        categories: {
          correctness: "off",
          suspicious: "off",
          pedantic: "off",
          perf: "off",
          style: "off",
          restriction: "off",
          nursery: "off",
        },
        jsPlugins: [
          {
            name: "sarj-testing-library",
            specifier: join(
              packageDirectory,
              "src/upstream/testing-library.js",
            ),
          },
        ],
        rules: { "sarj-testing-library/await-async-queries": "error" },
      }),
    );
    const source =
      "import { screen } from '@testing-library/react'; screen.findByText('Save');";
    writeFileSync(join(root, "probe.ts"), source);
    const args = [
      "--config",
      ".oxlintrc.json",
      "--format",
      "json",
      "--fix",
      "probe.ts",
    ];
    for (let pass = 0; pass < 2; pass++) {
      const result = spawnSync(process.execPath, [oxlintBinary, ...args], {
        cwd: root,
        encoding: "utf8",
        timeout: 30_000,
      });
      if (result.error) throw result.error;
      expect(result).toMatchObject({ status: 0, stderr: "" });
      expect(JSON.parse(result.stdout).diagnostics).toEqual([]);
      expect(readFileSync(join(root, "probe.ts"), "utf8")).toBe(
        "import { screen } from '@testing-library/react'; await screen.findByText('Save');",
      );
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
