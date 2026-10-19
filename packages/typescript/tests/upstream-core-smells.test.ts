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
const CONSTRUCTOR = "no-constructor-return";
const LOOP = "no-unreachable-loop";
const ELSE_IF = "no-lonely-if";
const WARNING_RULES = [CONSTRUCTOR, LOOP, ELSE_IF];
const SELECTED_RULES = new Set([
  ...WARNING_RULES,
  "arrow-body-style",
  "unicorn/no-useless-else",
  "unicorn/no-lonely-if",
  "unicorn/prefer-ternary",
  "@typescript-eslint/no-confusing-void-expression",
  "@typescript-eslint/strict-void-return",
  "no-invalid-regexp",
]);

type ReviewCase = readonly [name: string, code: string, expected: readonly string[], fixed?: string];

const REVIEW_CASES: readonly ReviewCase[] = [
  ["constructor returns a replacement object", "export class Box { value = 1; constructor() { return { value: 2 }; } }", [CONSTRUCTOR]],
  ["constructor returns an ignored primitive", "export class Box { constructor() { return 1; } }", [CONSTRUCTOR]],
  ["constructor conditionally returns a value", "export class Box { value = 1; constructor(replace: boolean) { if (replace) return { value: 2 }; } }", [CONSTRUCTOR]],
  ["constructor can return without a value", "export class Box { value = 1; constructor(stop: boolean) { if (stop) return; this.value = 2; } }", []],
  ["ordinary method can return a value", "export class Box { value() { return 1; } }", []],
  ["nested constructor callback owns its return", "export class Box { value: number; constructor() { this.value = [1].map((entry) => entry + 1)[0] ?? 0; } }", []],
  ["object method named constructor is an ordinary method", "export const factory = { constructor() { return 1; } };", []],
  ["for loop cannot reach its second iteration", "export function find(items: number[]) { for (const item of items) { if (item > 0) return item; throw new Error('missing'); } }", [LOOP]],
  ["while loop always breaks", "declare function perform(): void; export function run(ready: boolean) { while (ready) { perform(); break; } }", [LOOP]],
  ["do loop always returns", "export function run(ready: boolean) { do { return ready; } while (ready); }", [LOOP]],
  ["loop can continue before reaching an exit", "declare function perform(value: number): void; export function run(items: number[]) { for (const item of items) { if (item < 0) continue; perform(item); break; } }", []],
  ["conditional return permits later items", "export function find(items: number[]) { for (const item of items) { if (item > 0) return item; } return 0; }", []],
  ["inner exit leaves outer loop iterable", "declare function perform(value: number): void; export function run(items: number[]) { for (const item of items) { if (item > 0) { perform(item); break; } } }", []],
  ["else with only an if becomes else-if", "declare function one(): void; declare function two(): void; export function choose(a: boolean, b: boolean) { if (a) one(); else { if (b) two(); } }", [ELSE_IF], "declare function one(): void; declare function two(): void; export function choose(a: boolean, b: boolean) { if (a) one(); else if (b) two(); }"],
  ["else keeps work before its nested condition", "declare function prepare(): void; declare function one(): void; declare function two(): void; export function choose(a: boolean, b: boolean) { if (a) one(); else { prepare(); if (b) two(); } }", []],
  ["else keeps work after its nested condition", "declare function finish(): void; declare function one(): void; declare function two(): void; export function choose(a: boolean, b: boolean) { if (a) one(); else { if (b) two(); finish(); } }", []],
  ["else-if is already concise", "declare function one(): void; declare function two(): void; export function choose(a: boolean, b: boolean) { if (a) one(); else if (b) two(); }", []],
  ["static RegExp construction remains supported", 'export const expression = new RegExp("[a-z]+", "u");', []],
  ["static RegExp factory remains supported", 'export const expression = RegExp("hello", "i");', []],
  ["dynamic RegExp pattern needs its constructor", 'export function expression(pattern: string) { return new RegExp(pattern, "u"); }', []],
  ["dynamic RegExp flags need their constructor", 'export function expression(flags: string) { return new RegExp("hello", flags); }', []],
  ["literal regex needs no constructor", "export const expression = /hello/iu;", []],
  ["invalid pattern retains its existing owner without a duplicate preference warning", 'export function expression() { try { return new RegExp("["); } catch { return undefined; } }', ["no-invalid-regexp"]],
  ["shadowed RegExp has a separate contract", 'export function expression(RegExp: (pattern: string) => string) { return RegExp("hello"); }', []],
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

describe("additional upstream core smell warnings", () => {
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

  it.each(CONFIG_FACTORIES)("%s stages the core additions as warnings", async (_name, factory) => {
    const eslint = new ESLint({ cwd: FIXTURE_ROOT, overrideConfigFile: true, overrideConfig: factory({ tsconfigRootDir: FIXTURE_ROOT }) });
    const config = await eslint.calculateConfigForFile("typed-concision-probe.ts") as Linter.Config;
    for (const id of WARNING_RULES) expect(config?.rules?.[id]?.[0]).toBe(1);
    expect(config?.rules?.["no-promise-executor-return"]?.[0] ?? 0).toBe(0);
    expect(config?.rules?.["no-lone-blocks"]?.[0] ?? 0).toBe(0);
    expect(config?.rules?.["no-self-compare"]?.[0] ?? 0).toBe(0);
    expect(config?.rules?.["prefer-regex-literals"]?.[0] ?? 0).toBe(0);
    expect(config?.rules?.["@typescript-eslint/no-unused-private-class-members"]?.[0] ?? 0).toBe(0);
  });

  it("keeps warnings available without a type project", async () => {
    const eslint = linter(false);
    const [result] = await eslint.lintText('export class Box { value = 1; constructor() { return { value: 2 }; } } export function run(ready: boolean) { while (ready) { break; } }', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([CONSTRUCTOR, LOOP]);
  });

  it("supports an exact suppression for intentional constructor replacement", async () => {
    const [result] = await eslint.lintText('export class Box { value = 1; constructor() {\n// eslint-disable-next-line no-constructor-return -- this factory intentionally replaces the constructed instance\nreturn { value: 2 }; } }', { filePath: "typed-concision-probe.ts" });
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(({ ruleId }) => ruleId)).toEqual([CONSTRUCTOR]);
  });
});
