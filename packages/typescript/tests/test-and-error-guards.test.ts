import { fileURLToPath } from "node:url";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const PACKAGE_ROOT = fileURLToPath(new URL("../", import.meta.url));
const FIXTURE_ROOT = fileURLToPath(new URL("./fixtures/runs/", import.meta.url));
const VALID_EXPECT = "vitest/valid-expect";
const FOCUSED_TEST = "vitest/no-focused-tests";
const PRESERVE_CAUSE = "preserve-caught-error";
const FLOATING_PROMISE = "@typescript-eslint/no-floating-promises";
const SELECTED_RULES = new Set([VALID_EXPECT, FOCUSED_TEST, PRESERVE_CAUSE]);
type ConfigOptions = {
  tsconfigRootDir?: string;
  projectService?: boolean;
  testFrameworks?: string[];
  syntaxOnlyConfigFiles?: string[];
};
type ConfigFactory = (options: ConfigOptions) => Linter.Config[];
const STRICT_CONFIG_FACTORY = createConfig as ConfigFactory;
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", STRICT_CONFIG_FACTORY],
  ["application", createApplicationConfig as ConfigFactory],
];
type GuardCase = readonly [name: string, source: string, expected: readonly string[]];

const EXPECT_CASES: readonly GuardCase[] = [
  ["a bare expect asserts nothing", 'import { expect } from "vitest"; expect(1);', [VALID_EXPECT]],
  ["an imported alias still requires a matcher", 'import { expect as verify } from "vitest"; verify(1);', [VALID_EXPECT]],
  ["a matcher reference must be called", 'import { expect } from "vitest"; expect(1).toBe;', [VALID_EXPECT]],
  ["a modifier alone asserts nothing", 'import { expect } from "vitest"; expect(1).not;', [VALID_EXPECT]],
  ["an assertion needs its actual value", 'import { expect } from "vitest"; expect().toBe(1);', [VALID_EXPECT]],
  ["more than two expect arguments is invalid", 'import { expect } from "vitest"; expect(1, "context", "extra").toBe(1);', [VALID_EXPECT]],
  ["async assertion handling belongs to the typed promise owner", 'import { expect } from "vitest"; expect(Promise.resolve(1)).resolves.toBe(1);', []],
  ["an ordinary matcher is complete", 'import { expect } from "vitest"; expect(1).toBe(1);', []],
  ["a literal custom message is supported", 'import { expect } from "vitest"; expect(1, "context").toBe(1);', []],
  ["a dynamic custom message is supported", 'import { expect } from "vitest"; const message = getMessage(); expect(1, message).toBe(1);', []],
  ["asymmetric matcher factories are values", 'import { expect } from "vitest"; const value = expect.objectContaining({ ready: true });', []],
  ["assertion counts are not matcher chains", 'import { expect } from "vitest"; expect.assertions(1); expect.hasAssertions();', []],
  ["type assertions use a separate API", 'import { expectTypeOf } from "vitest"; expectTypeOf<number>().toEqualTypeOf<number>();', []],
  ["a locally defined expect is unrelated", 'function expect(value: number) { return value; } expect(1);', []],
  ["an expect from another package is unrelated", 'import { expect } from "custom-assertions"; expect(1);', []],
  ["an awaited async assertion is complete", 'import { expect } from "vitest"; await expect(Promise.resolve(1)).resolves.toBe(1);', []],
  ["a returned async assertion is complete", 'import { expect } from "vitest"; function verify() { return expect(Promise.resolve(1)).resolves.toBe(1); }', []],
  ["an awaited assertion collection is complete", 'import { expect } from "vitest"; await Promise.all([expect(Promise.resolve(1)).resolves.toBe(1)]);', []],
  ["a stored assertion may be awaited after other work", 'import { expect } from "vitest"; const error = new Error("expected"); const check = expect(Promise.reject(error)).rejects.toBe(error); await otherWork(); await check;', []],
  ["a stored assertion collection may be awaited later", 'import { expect } from "vitest"; const checks = Promise.all([expect(Promise.resolve(1)).resolves.toBe(1)]); await otherWork(); await checks;', []],
];

const FOCUS_CASES: readonly GuardCase[] = [
  ["test.only excludes other tests", 'import { test } from "vitest"; test.only("focused", () => {});', [FOCUSED_TEST]],
  ["it.only is also focused", 'import { it } from "vitest"; it.only("focused", () => {});', [FOCUSED_TEST]],
  ["describe.only excludes other suites", 'import { describe } from "vitest"; describe.only("focused", () => {});', [FOCUSED_TEST]],
  ["an imported test alias retains its owner", 'import { test as check } from "vitest"; check.only("focused", () => {});', [FOCUSED_TEST]],
  ["parameterized focused tests are caught", 'import { test } from "vitest"; test.only.each([1])("focused %i", () => {});', [FOCUSED_TEST]],
  ["the only option also focuses execution", 'import { test } from "vitest"; test("focused", { only: true }, () => {});', [FOCUSED_TEST]],
  ["ordinary test execution is supported", 'import { test } from "vitest"; test("ordinary", () => {});', []],
  ["an explicitly disabled only option is allowed", 'import { test } from "vitest"; test("ordinary", { only: false }, () => {});', []],
  ["skip has a different explicit meaning", 'import { test } from "vitest"; test.skip("pending", () => {});', []],
  ["an unrelated only method is allowed", 'const collection = { only(value: number) { return value; } }; collection.only(1);', []],
  ["a locally shadowed test has another owner", 'const test = { only(value: string) { return value; } }; test.only("ordinary");', []],
];

const CAUSE_CASES: readonly GuardCase[] = [
  ["an optional catch binding loses the original error", 'try { work(); } catch { throw new Error("failed"); }', [PRESERVE_CAUSE]],
  ["an optional binding also loses built-in subclasses", 'try { work(); } catch { throw new TypeError("failed"); }', [PRESERVE_CAUSE]],
  ["a named catch without cause loses the error", 'try { work(); } catch (error) { throw new Error("failed"); }', [PRESERVE_CAUSE]],
  ["an incorrect cause does not preserve the catch", 'try { work(); } catch (error) { throw new Error("failed", { cause: "other" }); }', [PRESERVE_CAUSE]],
  ["destructuring loses part of the error", 'try { work(); } catch ({ message }) { throw new Error(message); }', [PRESERVE_CAUSE]],
  ["the innermost catch owns the cause", 'try { work(); } catch (outer) { try { recover(); } catch (inner) { throw new Error("failed", { cause: outer }); } }', [PRESERVE_CAUSE]],
  ["a direct rethrow preserves identity", 'try { work(); } catch (error) { throw error; }', []],
  ["an explicit cause preserves the error", 'try { work(); } catch (error) { throw new Error("failed", { cause: error }); }', []],
  ["AggregateError has its options in argument three", 'try { work(); } catch (error) { throw new AggregateError([], "failed", { cause: error }); }', []],
  ["handling without rethrow needs no catch parameter", 'try { work(); } catch { recover(); }', []],
  ["nested functions have independent failures", 'try { work(); } catch { const later = () => { throw new Error("later"); }; schedule(later); }', []],
  ["a class static block has its own failure boundary", 'try { work(); } catch { class Later { static { throw new Error("later"); } } }', []],
  ["a shadowed Error constructor has unknown semantics", 'import { Error } from "custom-errors"; try { work(); } catch { throw new Error("custom"); }', []],
  ["a custom class is outside the configured built-ins", 'try { work(); } catch { throw new DomainError("custom"); }', []],
  ["spread options cannot be proven wrong", 'try { work(); } catch (error) { throw new Error("failed", { ...options }); }', []],
  ["a throw outside catch has no original cause", 'throw new Error("failed");', []],
];

function linter(factory = STRICT_CONFIG_FACTORY, options: ConfigOptions = {}, fix = false, rules = SELECTED_RULES): ESLint {
  const config = factory({ projectService: false, ...options }).map((entry) => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => rules.has(id))),
  }));
  return new ESLint({ cwd: PACKAGE_ROOT, overrideConfigFile: true, overrideConfig: config, fix });
}

describe("upstream test and error guards", () => {
  const eslint = linter();

  it.each([...EXPECT_CASES, ...FOCUS_CASES, ...CAUSE_CASES])("%s", async (_name, source, expected) => {
    const [result] = await eslint.lintText(source, { filePath: "src/unit.test.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(expected);
    expect(result?.messages.every(({ severity }) => severity === 1)).toBe(true);
  });

  it.each(CONFIG_FACTORIES)("%s scopes Vitest checks to opted-in test files", async (_name, factory) => {
    const cases = [
      { frameworks: ["vitest", "node"], path: "src/feature.test.ts", active: true },
      { frameworks: ["vitest"], path: "src/__tests__/feature.ts", active: true },
      { frameworks: ["vitest"], path: "src/feature.ts", active: false },
      { frameworks: ["node"], path: "src/node.test.ts", active: false },
      { frameworks: ["bun"], path: "src/feature.bun.test.ts", active: false },
      { frameworks: ["vitest", "bun"], path: "src/feature.bun.test.ts", active: false },
      { frameworks: ["vitest", "playwright"], path: "src/playwright/feature.test.ts", active: false },
      { frameworks: [], path: "src/feature.test.ts", active: false },
    ];
    const source = 'import { expect, test } from "vitest"; expect(1); test.only("focused", () => {});';
    for (const testCase of cases) {
      const scoped = linter(factory, { testFrameworks: testCase.frameworks });
      const [result] = await scoped.lintText(source, { filePath: testCase.path });
      expect(result?.fatalErrorCount).toBe(0);
      expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(testCase.active ? [VALID_EXPECT, FOCUSED_TEST] : []);
      const configured = await scoped.calculateConfigForFile(testCase.path) as Linter.Config;
      if (testCase.active) {
        expect(configured.rules?.[VALID_EXPECT]).toEqual([1, { alwaysAwait: false, asyncMatchers: ["toReject", "toResolve"], minArgs: 1, maxArgs: 2 }]);
        expect(configured.plugins?.["vitest"]?.rules?.["valid-expect"]?.meta?.fixable).toBeUndefined();
        expect(configured.rules?.[FOCUSED_TEST]).toEqual([1, { fixable: true }]);
      }
      expect(configured.rules?.[PRESERVE_CAUSE]).toEqual([1, { requireCatchParameter: true, errorClassNames: [] }]);
    }
  });

  it("keeps syntax-only guards available outside a type project", async () => {
    const fallback = linter(STRICT_CONFIG_FACTORY, { tsconfigRootDir: FIXTURE_ROOT, projectService: true, syntaxOnlyConfigFiles: ["**/tooling.test.ts"] });
    const [result] = await fallback.lintText('import { expect } from "vitest"; expect(1); try { work(); } catch { throw new Error("failed"); }', { filePath: "tooling.test.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([VALID_EXPECT, PRESERVE_CAUSE]);
  });

  it.each(CONFIG_FACTORIES)("%s leaves typed async assertions with their existing promise owner", async (_name, factory) => {
    const typed = linter(factory, { tsconfigRootDir: FIXTURE_ROOT, projectService: true }, false, new Set([...SELECTED_RULES, FLOATING_PROMISE]));
    const source = [
      'import { expect } from "vitest";',
      'expect(Promise.resolve(1)).resolves.toBe(1);',
      'void expect(Promise.resolve(2)).resolves.toBe(2);',
      'Promise.all([expect(Promise.resolve(3)).resolves.toBe(3)]);',
      'Promise.resolve(4);',
      'expect(5);',
      'await expect(Promise.resolve(6)).resolves.toBe(6);',
      'await Promise.all([expect(Promise.resolve(7)).resolves.toBe(7)]);',
      'const error = new Error("expected");',
      'const check = expect(Promise.reject(error)).rejects.toBe(error);',
      'await Promise.resolve();',
      'await check;',
      'const checks = Promise.all([expect(Promise.resolve(8)).resolves.toBe(8)]);',
      'await Promise.resolve();',
      'await checks;',
    ].join("\n");
    const [result] = await typed.lintText(source, { filePath: "tests/fixtures/runs/typed-concision-probe.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId, line, severity }) => ({ ruleId, line, severity }))).toEqual([
      { ruleId: FLOATING_PROMISE, line: 2, severity: 2 },
      { ruleId: FLOATING_PROMISE, line: 3, severity: 2 },
      { ruleId: FLOATING_PROMISE, line: 4, severity: 2 },
      { ruleId: FLOATING_PROMISE, line: 5, severity: 2 },
      { ruleId: VALID_EXPECT, line: 6, severity: 1 },
    ]);
    const locations = result?.messages.map(({ line, column }) => `${line}:${column}`) ?? [];
    expect(new Set(locations).size).toBe(locations.length);
  });

  it("limits syntax-only assertion analysis to structural checks", async () => {
    const fallback = linter(STRICT_CONFIG_FACTORY, { tsconfigRootDir: FIXTURE_ROOT, projectService: true, syntaxOnlyConfigFiles: ["**/tooling.test.ts"] });
    const [result] = await fallback.lintText('import { expect } from "vitest"; expect(Promise.resolve(1)).resolves.toBe(1); expect(2);', { filePath: "tooling.test.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([VALID_EXPECT]);
    expect(result?.messages[0]?.messageId).toBe("matcherNotFound");
  });

  it("supports exact, local suppressions without masking another guard", async () => {
    const source = [
      'import { expect, test } from "vitest";',
      "// eslint-disable-next-line vitest/valid-expect -- exercise incomplete assertion analysis",
      "expect(1);",
      '// eslint-disable-next-line vitest/no-focused-tests -- exercise focused execution analysis',
      'test.only("focused", () => {});',
      "// eslint-disable-next-line preserve-caught-error -- deliberately exercise a cause-losing boundary",
      'try { work(); } catch { throw new Error("failed"); }',
      "expect(2);",
    ].join("\n");
    const [result] = await eslint.lintText(source, { filePath: "src/suppressions.test.ts" });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([VALID_EXPECT]);
    expect(result?.suppressedMessages.map(({ ruleId }) => ruleId)).toEqual([VALID_EXPECT, FOCUSED_TEST, PRESERVE_CAUSE]);
  });

  it("fixes focused execution to a stable result", async () => {
    const fixer = linter(STRICT_CONFIG_FACTORY, {}, true);
    const source = 'import { expect, test } from "vitest"; test.only("works", () => { expect(1).toBe(1); });';
    const [first] = await fixer.lintText(source, { filePath: "src/fixes.test.ts" });
    const fixed = first?.output ?? source;
    expect(fixed).toBe('import { expect, test } from "vitest"; test("works", () => { expect(1).toBe(1); });');
    expect(first?.messages).toEqual([]);
    const [second] = await fixer.lintText(fixed, { filePath: "src/fixes.test.ts" });
    expect(second?.output).toBeUndefined();
    expect(second?.messages).toEqual([]);
  });

  it("suggests preserving cause without applying a semantic edit automatically", async () => {
    const source = 'try { work(); } catch (error) { throw new Error("failed"); }';
    const fixer = linter(STRICT_CONFIG_FACTORY, {}, true);
    const [result] = await fixer.lintText(source, { filePath: "src/error.ts" });
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([PRESERVE_CAUSE]);
    const suggestion = result?.messages[0]?.suggestions?.[0];
    expect(suggestion?.messageId).toBe("includeCause");
    expect(suggestion).toBeDefined();
    if (suggestion === undefined) throw new Error("expected a cause-preserving suggestion");
    const fixed = source.slice(0, suggestion.fix.range[0]) + suggestion.fix.text + source.slice(suggestion.fix.range[1]);
    const [second] = await fixer.lintText(fixed, { filePath: "src/error.ts" });
    expect(second?.output).toBeUndefined();
    expect(second?.messages).toEqual([]);
  });
});
