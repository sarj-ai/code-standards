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
    "let value = 0; export async function set(next: number) { return value = next; }",
    "let value = 0; export const set = async (next: number) => value = next;",
    "let value = 0; export const callback: (next: number) => void = next => value = next;",
    "let value = 0; export function total(values: number[]) { values.forEach(next => value += next); return value; }",
    "let value = 0; export function set(next: number) { return { value: value = next }; }",
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
    "let first = 0, second = 0; export function choose(flag: boolean, next: number) { return flag ? (first = next) : (second = next); }",
    "let first = 0, second = 0; export function set(next: number) { return (first = (second = next)); }",
    "let value = 0; export const callback: (next: number) => void = next => (value = next);",
    "let value = 0; export function total(values: number[]) { values.forEach(next => { value += next; }); return value; }",
    "let value = 0; export function factory() { return { set(next: number) { value = next; return value; } }; }",
    "let value = 0; export function set(next: number) { return (function () { value = next; return value; })(); }",
    "let value = 0; export function set(next: { value: number }) { return ({ value } = next); }",
    "let task: Promise<number>; export async function read(next: Promise<number>) { return await (task = next); }",
    "let first = 0, second = 0; export function set(next: number) { second = next; first = second; return first; }",
  ])("preserves comparisons, explicit changes and deliberately grouped memoization: %s", async source => {
    const [result] = await eslint.lintText(source, { filePath: "example.ts" });
    expect(result?.messages).toEqual([]);
  });

  it.each([
    "let first = 0, second = 0; export function set(next: number) { return first = second = next; }",
    "let first = 0, second = 0; export function set(next: number) { return (first = second = next); }",
    "let first = 0, second = 0; export function choose(flag: boolean, next: number) { return flag ? first = next : second = next; }",
  ])("keeps multiple writes reviewable without depending on upstream report multiplicity: %s", async source => {
    const [result] = await eslint.lintText(source, { filePath: "example.ts" });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.length).toBeGreaterThan(0);
    expect(result?.messages.every(message => message.ruleId === RULE_ID && message.severity === 1 && message.fix === undefined)).toBe(true);
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

it("preserves local chained-assignment behavior with the formatter-stable separate-statement remedy", () => {
  const chained: unknown = runInNewContext("let first = 0, second = 0; function set(next) { return first = second = next; } ({ returned: set(3), first, second });");
  const separate: unknown = runInNewContext("let first = 0, second = 0; function set(next) { second = next; first = second; return first; } ({ returned: set(3), first, second });");
  expect(chained).toEqual({ returned: 3, first: 3, second: 3 });
  expect(separate).toEqual(chained);
});
