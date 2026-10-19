import { resolve } from "node:path";
import { runInNewContext } from "node:vm";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig as createStrictConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_DIR = resolve(import.meta.dirname, "fixtures/runs");
const RULE_ID = "no-return-assign";
type ConfigFactory = (options?: { tsconfigRootDir?: string; projectService?: boolean }) => Linter.Config[];
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createStrictConfig],
  ["application", createApplicationConfig],
];

describe.each(CONFIG_FACTORIES)("%s returned assignment policy", (_name, createConfig) => {
  const config = createConfig({ tsconfigRootDir: FIXTURE_DIR, projectService: false }).map(entry => ({
      ...entry,
      rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => id === RULE_ID)),
  }));
  const eslint = new ESLint({ cwd: FIXTURE_DIR, overrideConfigFile: true, overrideConfig: config });

  it.each([
    "let value = 0; export function matches(next: number) { return value = next; }",
    "let value = 0; export function add(next: number) { return value += next; }",
    "let value = 0; export const matches = (next: number) => value = next;",
    "export function matches(next: number) { return state.value = next; }",
    "export const matches = (next: number) => state.value = next;",
    "let value = 0; export function choose(flag: boolean) { return flag ? value = 1 : value; }",
    "let cached: object | undefined; export const read = () => cached ??= load();",
    "let value = 0; export function factory() { return () => value = 1; }",
  ])("warns without guessing whether assignment or comparison was intended: %s", async source => {
    const [result] = await eslint.lintText(source, { filePath: "example.ts" });
    expect(result?.messages.map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([{ ruleId: RULE_ID, severity: 1 }]);
    expect(result?.messages[0]?.fix).toBeUndefined();
  });

  it.each([
    "let value = 0; export function matches(next: number) { return value === next; }",
    "let value = 0; export function set(next: number) { value = next; return value; }",
    "let value = 0; export function set(next: number) { return (value = next); }",
    "let cached: object | undefined; export const read = () => (cached ??= load());",
    "let cached: object | undefined; export function read() { return (cached ??= load()); }",
    "let cached: object | undefined; export function read() { cached ??= load(); return cached; }",
    "export function read() { return state.value; }",
    "export const read = () => state.value;",
  ])("preserves comparisons, explicit changes and deliberately grouped memoization: %s", async source => {
    const [result] = await eslint.lintText(source, { filePath: "example.ts" });
    expect(result?.messages).toEqual([]);
  });

  it("supports an exact local exception for an intentional API contract", async () => {
    const [result] = await eslint.lintText([
      "let value = 0;",
      "// eslint-disable-next-line no-return-assign -- This legacy callback deliberately returns the newly stored value.",
      "export const store = (next: number) => value = next;",
    ].join("\n"), { filePath: "example.ts" });
    expect(result?.messages).toEqual([]);
  });

  it("retains the warning and source when automatic fixing is requested", async () => {
    const fix = new ESLint({ cwd: FIXTURE_DIR, overrideConfigFile: true, overrideConfig: config, fix: true });
    const [result] = await fix.lintText("let value = 0; export function matches(next: number) { return value = next; }", { filePath: "example.ts" });
    expect(result?.messages.map(message => message.ruleId)).toEqual([RULE_ID]);
    expect(result?.output).toBeUndefined();
  });
});

it("demonstrates why changing assignment to comparison needs intent review", () => {
  expect(runInNewContext("let value = 0; function matches(next) { return value = next; } ({ returned: matches(3), value });")).toEqual({ returned: 3, value: 3 });
  expect(runInNewContext("let value = 0; function matches(next) { return value === next; } ({ returned: matches(3), value });")).toEqual({ returned: false, value: 0 });
  expect(runInNewContext("let value = 0; function store(next) { value = next; return value; } ({ returned: store(3), value });")).toEqual({ returned: 3, value: 3 });
});
