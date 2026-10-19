import { fileURLToPath } from "node:url";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_ROOT = fileURLToPath(new URL("./fixtures/runs/", import.meta.url));
type ConfigFactory = (options: { tsconfigRootDir: string; projectService?: boolean }) => Linter.Config[];
const STRICT_CONFIG_FACTORY = createConfig as ConfigFactory;
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", STRICT_CONFIG_FACTORY],
  ["application", createApplicationConfig as ConfigFactory],
];
const BACKTRACKING = "regexp/no-super-linear-backtracking";
const MISSING_GLOBAL = "regexp/no-missing-g-flag";
const DUPLICATE = "regexp/no-dupe-disjunctions";
const INVALID = "no-invalid-regexp";
const SELECTED_RULES = new Set([BACKTRACKING, MISSING_GLOBAL, DUPLICATE, INVALID]);

type ReviewCase = readonly [name: string, code: string, expected: readonly string[], fixed?: string];

const REVIEW_CASES: readonly ReviewCase[] = [
  ["literal matchAll requires a global regex", 'export const matches = "abc".matchAll(/a/);', [MISSING_GLOBAL], 'export const matches = "abc".matchAll(/a/g);'],
  ["literal replaceAll requires a global regex", 'export const replaced = "abc".replaceAll(/a/i, "x");', [MISSING_GLOBAL], 'export const replaced = "abc".replaceAll(/a/ig, "x");'],
  ["constructor argument requires a global regex", 'export const matches = "abc".matchAll(new RegExp("a", "i"));', [MISSING_GLOBAL], 'export const matches = "abc".matchAll(new RegExp("a", "ig"));'],
  ["locally referenced pattern requires a global regex", 'const expression = /a/; export const matches = "abc".matchAll(expression);', [MISSING_GLOBAL]],
  ["aliased regex reference is followed", 'const expression = /a/; const alias = expression; export const matches = "abc".matchAll(alias);', [MISSING_GLOBAL]],
  ["dynamic flags are outside static proof", 'export function matches(flags: string) { return "abc".matchAll(new RegExp("a", flags)); }', []],
  ["shadowed RegExp can return a string accepted by matchAll", 'export function matches(RegExp: (pattern: string) => string) { return "abc".matchAll(RegExp("a")); }', []],
  ["global matchAll is already correct", 'export const matches = "abc".matchAll(/a/gi);', []],
  ["global replaceAll is already correct", 'export const replaced = "abc".replaceAll(/a/g, "x");', []],
  ["string replaceAll argument does not require a regex flag", 'export const replaced = "abc".replaceAll("a", "x");', []],
  ["ordinary match permits non-global regexes", 'export const match = "abc".match(/a/);', []],
  ["ordinary replace permits non-global regexes", 'export const replaced = "abc".replace(/a/, "x");', []],
  ["unrelated matchAll method has its own contract", 'export const matcher = { matchAll(expression: RegExp) { return expression.source; } }; export const result = matcher.matchAll(/a/);', []],
  ["unrelated replaceAll method has its own contract", 'export const matcher = { replaceAll(expression: RegExp) { return expression.source; } }; export const result = matcher.replaceAll(/a/);', []],
  ["invalid constructor pattern retains its existing owner", 'export function expression() { try { return new RegExp("["); } catch { return undefined; } }', [INVALID]],
];

function focusedConfig(typed: boolean): Linter.Config[] {
  return STRICT_CONFIG_FACTORY({ tsconfigRootDir: FIXTURE_ROOT, projectService: typed }).map((entry) => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => SELECTED_RULES.has(id))),
  }));
}

function linter(typed: boolean, fix = false): ESLint {
  return new ESLint({ cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: focusedConfig(typed), fix });
}

describe("upstream regexp safety policy", () => {
  const eslint = linter(true);
  const fixer = linter(true, true);

  it.each(REVIEW_CASES)("%s", async (_name, code, expected, fixed) => {
    const [result] = await eslint.lintText(code, { filePath: "typed-concision-probe.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(expected);
    expect(result?.messages.every(({ severity }) => severity === 1)).toBe(true);
    if (fixed !== undefined) {
      const [first] = await fixer.lintText(code, { filePath: "typed-concision-probe.ts" });
      expect(first?.output).toBe(fixed);
      expect(first?.messages).toEqual([]);
      const [second] = await fixer.lintText(fixed, { filePath: "typed-concision-probe.ts" });
      expect(second?.output).toBeUndefined();
      expect(second?.messages).toEqual([]);
    }
  });

  it.each(CONFIG_FACTORIES)("%s enables only the admitted global-flag warning", async (_name, factory) => {
    const eslint = new ESLint({ cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: factory({ tsconfigRootDir: FIXTURE_ROOT }) });
    const config = await eslint.calculateConfigForFile("typed-concision-probe.ts") as Linter.Config;
    const backtracking = config.rules?.[BACKTRACKING];
    expect((Array.isArray(backtracking) ? backtracking[0] : backtracking) ?? 0).toBe(0);
    const disjunctions = config.rules?.[DUPLICATE];
    expect((Array.isArray(disjunctions) ? disjunctions[0] : disjunctions) ?? 0).toBe(0);
    expect(config.rules?.[MISSING_GLOBAL]).toEqual([1, { strictTypes: true }]);
    const enabled = Object.entries(config.rules ?? {})
      .filter(([id, setting]) => id.startsWith("regexp/") && (Array.isArray(setting) ? setting[0] : setting) !== 0)
      .map(([id]) => id);
    expect(enabled).toEqual([MISSING_GLOBAL]);
    const focused = new ESLint({
      cwd: FIXTURE_ROOT,
      overrideConfigFile: true,
      overrideConfig: factory({ tsconfigRootDir: FIXTURE_ROOT }).map((entry) => ({
        ...entry,
        rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => SELECTED_RULES.has(id))),
      })),
    });
    const [result] = await focused.lintText('export const matches = "abc".matchAll(/a/);', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([MISSING_GLOBAL]);
  });

  it("retains literal safety analysis without a type project", async () => {
    const eslint = linter(false);
    const [result] = await eslint.lintText('export const matches = "abc".matchAll(/a/);', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([MISSING_GLOBAL]);
  });

  it("uses receiver types to distinguish String methods", async () => {
    const [result] = await eslint.lintText('export function matches(input: string) { return input.matchAll(/a/); } export function custom(input: { matchAll(expression: RegExp): string }) { return input.matchAll(/a/); }', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([MISSING_GLOBAL]);
  });

  it("supports exact suppressions for reviewed intentional patterns", async () => {
    const [result] = await eslint.lintText('// eslint-disable-next-line regexp/no-missing-g-flag -- exercise the intentional native failure in a reproduction\nexport const matches = "abc".matchAll(/a/);', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(({ ruleId }) => ruleId)).toEqual([MISSING_GLOBAL]);
  });

  it("does not mutate a shared regex while fixing a missing global flag", async () => {
    const code = 'const expression = /a/; export const first = expression.test("a"); export const matches = "abc".matchAll(expression); export const second = expression.test("a");';
    const [result] = await fixer.lintText(code, { filePath: "typed-concision-probe.ts" });
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([MISSING_GLOBAL]);
    expect(result?.messages[0]?.fix).toBeUndefined();
  });

  it.each([
    ["universal accepting suffix", 'export function match(input: string) { return /^\\s*([\\s\\S]*)$/.exec(input); }'],
    ["real nested-quantifier hazard", 'export function match(input: string) { return /^(a+)+$/.exec(input); }'],
    ["real repeated-alternative hazard", 'export function match(input: string) { return /^(?:a.|.b)+$/.exec(input); }'],
    ["backreference-dependent capturing alternatives", 'export const expression = /^(?:(a)|(a))\\2$/;'],
    ["backreference-dependent alternative with an unsafe native suggestion", 'export const expression = /^(?:(a)|a)\\1$/;'],
    ["universal accepting suffix after overlapping alternatives", 'export function match(input: string) { return /^(?:a.|.b)+[\\s\\S]*$/.exec(input); }'],
    ["fragments preserve alternatives needed by a later backreference", 'const fragment = /(?:(a)|a)/.source; export const expression = new RegExp(`^${fragment}\\\\1$`);'],
  ])("keeps deferred regex analyses inactive for %s", async (_name, code) => {
    const [result] = await fixer.lintText(code, { filePath: "typed-concision-probe.ts" });
    expect(result?.messages).toEqual([]);
    expect(result?.output).toBeUndefined();
  });

  it("proves why removing a duplicate-looking alternative changes backreference matching", () => {
    const original = new RegExp("^(?:(a)|a)\\1$");
    const suggested = new RegExp("^(?:(a))\\1$");
    expect(original.test("a")).toBe(true);
    expect(original.test("aa")).toBe(true);
    expect(suggested.test("a")).toBe(false);
    expect(suggested.test("aa")).toBe(true);
  });
});
