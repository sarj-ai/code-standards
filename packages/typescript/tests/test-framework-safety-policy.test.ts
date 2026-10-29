import { ESLint, type Linter } from "eslint";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig as createStrictConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

type Framework = "node" | "vitest" | "bun" | "playwright";
type ConfigFactory = (options: {
  projectService: boolean;
  testFrameworks: Framework[];
  tsconfigRootDir?: string;
  syntaxOnlyConfigFiles?: string[];
  playwrightTestFiles?: string[];
}) => Linter.Config[];

const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createStrictConfig],
  ["application", createApplicationConfig],
];
const NODE_IMPORTS = 'import test from "node:test"; import assert from "node:assert/strict"; ';
const VITEST_IMPORTS = 'import { test, expect } from "vitest"; ';
const CASES = [
  {
    rule: "node-test/no-late-test-activity",
    framework: "node",
    path: "src/activity.test.ts",
    invalid: NODE_IMPORTS + 'test("checks", () => { setImmediate(() => assert.equal(actual, expected)); });',
    valid: [
      NODE_IMPORTS + 'test("checks", async () => { await new Promise(resolve => setImmediate(() => { assert.equal(actual, expected); resolve(); })); });',
      NODE_IMPORTS + 'test("checks", (t, done) => { setImmediate(() => { assert.equal(actual, expected); done(); }); });',
    ],
  },
  {
    rule: "node-test/no-callback-and-promise",
    framework: "node",
    path: "src/completion.test.ts",
    invalid: NODE_IMPORTS + 'test("checks", async (t, done) => { done(); });',
    valid: [
      NODE_IMPORTS + 'test("checks", async t => { await work(); });',
      NODE_IMPORTS + 'test("checks", (t, done) => { done(); });',
      'function test(name, callback) {} test("checks", async (t, done) => { done(); });',
    ],
  },
  {
    rule: "node-test/no-mock-timers-destructured-import",
    framework: "node",
    path: "src/captured-timer.test.ts",
    invalid: NODE_IMPORTS + 'import { setTimeout } from "node:timers"; test("checks", t => { t.mock.timers.enable({ apis: ["setTimeout"] }); setTimeout(work, 1); });',
    valid: [
      NODE_IMPORTS + 'test("checks", t => { t.mock.timers.enable({ apis: ["setTimeout"] }); setTimeout(work, 1); });',
      NODE_IMPORTS + 'import { setTimeout } from "node:timers"; test("checks", t => { t.mock.timers.enable({ apis: ["Date"] }); setTimeout(work, 1); });',
      NODE_IMPORTS + 'import { setInterval } from "node:timers"; test("checks", t => { t.mock.timers.enable({ apis: ["setTimeout"] }); setInterval(work, 1); });',
    ],
  },
  {
    rule: "node-test/no-duplicate-mock-timers-enable",
    framework: "node",
    path: "src/timer-state.test.ts",
    invalid: NODE_IMPORTS + 'test("checks", t => { t.mock.timers.enable({ apis: ["Date"] }); t.mock.timers.enable({ apis: ["Date"] }); });',
    valid: [
      NODE_IMPORTS + 'test("checks", t => { t.mock.timers.enable({ apis: ["Date"] }); t.mock.timers.reset(); t.mock.timers.enable({ apis: ["Date"] }); });',
      NODE_IMPORTS + 'test("first", t => { t.mock.timers.enable({ apis: ["Date"] }); }); test("second", t => { t.mock.timers.enable({ apis: ["Date"] }); });',
    ],
  },
  {
    rule: "vitest/require-local-test-context-for-concurrent-snapshots",
    framework: "vitest",
    path: "src/snapshot.test.ts",
    invalid: VITEST_IMPORTS + 'test.concurrent("checks", () => { expect(actual).toMatchSnapshot(); });',
    valid: [
      VITEST_IMPORTS + 'test.concurrent("checks", ({ expect }) => { expect(actual).toMatchSnapshot(); });',
      VITEST_IMPORTS + 'test.concurrent("checks", context => { context.expect(actual).toMatchSnapshot(); });',
      VITEST_IMPORTS + 'test("checks", () => { expect(actual).toMatchSnapshot(); });',
    ],
  },
  {
    rule: "playwright/no-unsafe-references",
    framework: "playwright",
    path: "src/scope.playwright.ts",
    invalid: 'const expected = "ready"; await page.evaluate(() => document.title === expected);',
    valid: [
      'const expected = "ready"; await page.evaluate(value => document.title === value, expected);',
      "await page.evaluate(() => document.title);",
      "interface Result { value: string }; await page.evaluate((): Result => ({ value: document.title }));",
    ],
  },
] as const;
const NEW_RULES = CASES.map(testCase => testCase.rule);

function focusedConfig(factory: ConfigFactory, frameworks: Framework[], ruleIds: readonly string[]): Linter.Config[] {
  return factory({ projectService: false, testFrameworks: frameworks }).map(entry => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => ruleIds.includes(id))),
  }));
}

function linter(factory: ConfigFactory, frameworks: Framework[], ruleIds: readonly string[], fix = false): ESLint {
  return new ESLint({
    overrideConfigFile: true,
    overrideConfig: focusedConfig(factory, frameworks, ruleIds),
    fix,
  });
}

describe.each(CONFIG_FACTORIES)("%s test framework safety opt-ins", (_name, factory) => {
  it.each(CASES)("$rule warns on its defect and accepts valid boundaries", async testCase => {
    const eslint = linter(factory, [testCase.framework], [testCase.rule]);
    const [invalid] = await eslint.lintText(testCase.invalid, { filePath: testCase.path });
    expect(invalid?.messages.map(message => [message.ruleId, message.severity])).toEqual([[testCase.rule, 1]]);
    expect(invalid?.errorCount).toBe(0);
    for (const source of testCase.valid) {
      const [valid] = await eslint.lintText(source, { filePath: testCase.path });
      expect(valid?.messages).toEqual([]);
    }
  });

  it.each(CASES)("$rule obeys explicit framework opt-outs", async testCase => {
    const otherFrameworks = (["node", "vitest", "bun", "playwright"] as const)
      .filter(framework => framework !== testCase.framework);
    for (const frameworks of [[], otherFrameworks]) {
      const eslint = linter(factory, frameworks, [testCase.rule]);
      const [result] = await eslint.lintText(testCase.invalid, { filePath: testCase.path });
      expect(result?.messages).toEqual([]);
    }
  });

  it("keeps concurrent snapshot advice out of Bun and Playwright overrides", async () => {
    const eslint = linter(factory, ["node", "vitest", "bun", "playwright"], NEW_RULES);
    for (const [path, importSource] of [
      ["src/concurrent.bun.test.ts", "bun:test"],
      ["playwright/concurrent.spec.ts", "@playwright/test"],
    ]) {
      const source = `import { test, expect } from "${importSource}"; test.concurrent("checks", () => { expect(actual).toMatchSnapshot(); });`;
      const [result] = await eslint.lintText(source, { filePath: path });
      expect(result?.messages).toEqual([]);
    }
  });

  it("recognizes Node ownership without treating other runners as node:test", async () => {
    const eslint = linter(factory, ["node", "vitest", "bun", "playwright"], NEW_RULES);
    for (const [path, importSource] of [
      ["src/unit.test.ts", "vitest"],
      ["src/unit.bun.test.ts", "bun:test"],
      ["playwright/unit.spec.ts", "@playwright/test"],
    ]) {
      const source = `import { test } from "${importSource}"; test("checks", async (t, done) => { done(); });`;
      const [result] = await eslint.lintText(source, { filePath: path });
      expect(result?.messages).toEqual([]);
    }
  });

  it("does not apply browser-scope checks outside Playwright-owned paths", async () => {
    const eslint = linter(factory, ["node", "vitest", "bun", "playwright"], NEW_RULES);
    const source = 'const expected = "ready"; await page.evaluate(() => document.title === expected);';
    for (const filePath of ["src/unit.test.ts", "src/unit.bun.test.ts", "src/main.ts"]) {
      const [result] = await eslint.lintText(source, { filePath });
      expect(result?.messages).toEqual([]);
    }
  });

  it("keeps unsafe browser captures manual-only even with eslint --fix", async () => {
    const rule = "playwright/no-unsafe-references";
    const eslint = linter(factory, ["playwright"], [rule], true);
    const source = 'const expected = "ready"; const read = () => expected; await page.evaluate(() => read() === expected);';
    const [first] = await eslint.lintText(source, { filePath: "src/scope.playwright.ts" });
    expect(first?.messages.map(message => [message.ruleId, message.severity])).toEqual([[rule, 1], [rule, 1]]);
    expect(first?.messages.every(message => message.fix === undefined && message.suggestions === undefined)).toBe(true);
    expect(first?.fixableWarningCount).toBe(0);
    expect(first?.output).toBeUndefined();
    const [second] = await eslint.lintText(source, { filePath: "src/scope.playwright.ts" });
    expect(second?.messages).toEqual(first?.messages);
    expect(second?.output).toBeUndefined();
    const metadata = eslint.getRulesMetaForResults(first === undefined ? [] : [first])[rule];
    expect(metadata?.fixable).toBeUndefined();
    expect(metadata?.hasSuggestions).toBe(false);
  });

  it("extends existing await errors to locator promises and retains safe aggregation", async () => {
    const rule = "playwright/missing-playwright-await";
    const eslint = linter(factory, ["playwright"], [rule]);
    const [invalid] = await eslint.lintText('page.getByRole("button").count();', { filePath: "src/count.playwright.ts" });
    expect(invalid?.messages.map(message => [message.ruleId, message.severity])).toEqual([[rule, 2]]);
    for (const source of [
      'await page.getByRole("button").count();',
      'await Promise.all([page.getByRole("button").count()]);',
      'const pending = page.getByRole("button").count(); await pending;',
    ]) {
      const [valid] = await eslint.lintText(source, { filePath: "src/count.playwright.ts" });
      expect(valid?.messages).toEqual([]);
    }
  });

  it("selects one locator-promise authority across typed and syntax-only files", async () => {
    const root = fileURLToPath(new URL("./fixtures/runs/", import.meta.url));
    const ruleIds = ["playwright/missing-playwright-await", "@typescript-eslint/no-floating-promises"];
    const declarations = "declare const page: { getByRole(role: string): { count(): Promise<number> } }; ";
    for (const testCase of [
      { syntax: [], playwright: ["**/example.ts"], expected: [["@typescript-eslint/no-floating-promises", 2]] },
      { syntax: ["**/example.ts"], playwright: ["**/example.ts"], expected: [["playwright/missing-playwright-await", 2]] },
      { syntax: ["**/example.ts"], playwright: ["**/*.playwright.ts"], expected: [] },
    ]) {
      const config = factory({
        projectService: true,
        tsconfigRootDir: root,
        testFrameworks: ["playwright"],
        playwrightTestFiles: testCase.playwright,
        syntaxOnlyConfigFiles: testCase.syntax,
      }).map(entry => ({
        ...entry,
        rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => ruleIds.includes(id))),
      }));
      const eslint = new ESLint({ cwd: root, overrideConfigFile: true, overrideConfig: config });
      const [result] = await eslint.lintText(declarations + 'page.getByRole("button").count();', { filePath: "example.ts" });
      expect(result?.messages.map(message => [message.ruleId, message.severity])).toEqual(testCase.expected);
      for (const source of [
        'await page.getByRole("button").count();',
        'await Promise.all([page.getByRole("button").count()]);',
        'const pending = page.getByRole("button").count(); await pending;',
      ]) {
        const [valid] = await eslint.lintText(declarations + source, { filePath: "example.ts" });
        expect(valid?.messages).toEqual([]);
      }
    }
  });

  it("preserves rejected upstream opt-ins", async () => {
    const eslint = new ESLint({
      overrideConfigFile: true,
      overrideConfig: factory({ projectService: true, testFrameworks: ["node", "vitest", "playwright"] }),
    });
    const config: Linter.Config = await eslint.calculateConfigForFile("src/rejected.test.ts") as Linter.Config;
    for (const rule of [
      "@typescript-eslint/strict-boolean-expressions",
      "node-test/no-misused-context-hook",
      "node-test/no-mock-module-after-import",
      "vitest/require-awaited-expect-poll",
    ]) {
      const setting = config.rules?.[rule];
      expect(setting === undefined || (Array.isArray(setting) ? setting[0] : setting) === 0).toBe(true);
    }
  });

  it("supports an exact local suppression for warning-first adoption", async () => {
    const rule = "playwright/no-unsafe-references";
    const eslint = linter(factory, ["playwright"], [rule]);
    const source = `const expected = "ready";\n// eslint-disable-next-line ${rule} -- browser fixture supplies the matching global\nawait page.evaluate(() => document.title === expected);`;
    const [result] = await eslint.lintText(source, { filePath: "src/scope.playwright.ts" });
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(message => message.ruleId)).toEqual([rule]);
  });

  it("accepts a reasoned local suppression for synchronously flushed native timers", async () => {
    const rule = "node-test/no-late-test-activity";
    const eslint = new ESLint({
      overrideConfigFile: true,
      overrideConfig: [
        ...focusedConfig(factory, ["node"], [rule]),

        { linterOptions: { reportUnusedDisableDirectives: "off" } },
      ],
    });
    const source = [
      NODE_IMPORTS,
      'test("flushes", t => {',
      '  t.mock.timers.enable({ apis: ["setTimeout"] });',
      "  let flushed = false;",
      `  // eslint-disable-next-line ${rule} -- runAll synchronously executes this mocked timer before the test returns`,
      "  setTimeout(() => { flushed = true; assert.equal(flushed, true); }, 1);",
      "  t.mock.timers.runAll();",
      "  assert.equal(flushed, true);",
      "});",
    ].join("\n");
    const [result] = await eslint.lintText(source, { filePath: "src/native-clock.test.ts" });
    expect(result?.messages).toEqual([]);
  });
});
