import { fileURLToPath } from "node:url";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_ROOT = fileURLToPath(new URL("./fixtures/runs/", import.meta.url));
type ConfigFactory = (options: {
  tsconfigRootDir: string;
  projectService?: boolean;
}) => Linter.Config[];
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createConfig as ConfigFactory],
  ["application", createApplicationConfig as ConfigFactory],
];
const NESTED_IF = "unicorn/no-lonely-if";
const SCOPING_IIFE = "unicorn/prefer-block-statement-over-iife";
const ELSE_IF = "no-lonely-if";
const USELESS_ELSE = "unicorn/no-useless-else";
const SELECTED_RULES = new Set([
  NESTED_IF,
  SCOPING_IIFE,
  ELSE_IF,
  USELESS_ELSE,
  "@typescript-eslint/no-unnecessary-condition",
  "@typescript-eslint/no-unnecessary-type-conversion",
  "@typescript-eslint/strict-boolean-expressions",
  "unicorn/prefer-combined-guards",
]);

type ReviewCase = readonly [
  name: string,
  code: string,
  expected: readonly string[],
  fixed?: string,
];

const REVIEW_CASES: readonly ReviewCase[] = [
  [
    "nested guards have one combined condition",
    "export function run(left: boolean, right: boolean, consume: () => void) { if (left) { if (right) { consume(); } } }",
    [NESTED_IF],
    "export function run(left: boolean, right: boolean, consume: () => void) { if (left && right) { consume(); } }",
  ],
  [
    "combining conditions preserves short circuit calls",
    "declare function first(): boolean; declare function second(): boolean; declare function consume(): void; if (first()) { if (second()) { consume(); } }",
    [NESTED_IF],
    "declare function first(): boolean; declare function second(): boolean; declare function consume(): void; if (first() && second()) { consume(); }",
  ],
  [
    "logical expressions retain their original grouping",
    "export function run(left: boolean, fallback: boolean, right: boolean, consume: () => void) { if (left || fallback) { if (right) { consume(); } } }",
    [NESTED_IF],
    "export function run(left: boolean, fallback: boolean, right: boolean, consume: () => void) { if ((left || fallback) && right) { consume(); } }",
  ],
  [
    "an outer alternative needs separate branches",
    "export function run(left: boolean, right: boolean, consume: () => void, recover: () => void) { if (left) { if (right) { consume(); } } else { recover(); } }",
    [],
  ],
  [
    "an inner alternative must keep its outer condition",
    "export function run(left: boolean, right: boolean, consume: () => void, recover: () => void) { if (left) { if (right) { consume(); } else { recover(); } } }",
    [],
  ],
  [
    "a sibling statement prevents guard merging",
    "export function run(left: boolean, right: boolean, consume: () => void) { if (left) { consume(); if (right) { consume(); } } }",
    [],
  ],
  [
    "a lexical IIFE becomes a block",
    "export function run(consume: (answer: number) => void) { (() => { const answer = 42; consume(answer); })(); }",
    [SCOPING_IIFE],
    "export function run(consume: (answer: number) => void) { { const answer = 42; consume(answer); } }",
  ],
  [
    "ordinary functions used only for scope also become blocks",
    "export function run(consume: (answer: number) => void) { (function () { const answer = 7; consume(answer); })(); }",
    [SCOPING_IIFE],
    "export function run(consume: (answer: number) => void) { { const answer = 7; consume(answer); } }",
  ],
  [
    "an IIFE return remains local to its function",
    "export function run(stop: boolean, consume: () => void) { (() => { if (stop) return; consume(); })(); }",
    [],
  ],
  [
    "var needs its function scope",
    "export function run(consume: (answer: number) => void) { (function () { var answer = 42; consume(answer); })(); }",
    [],
  ],
  [
    "an asynchronous IIFE owns its promise boundary",
    "export function run(consume: () => Promise<void>) { (async () => { await consume(); })(); }",
    [],
  ],
  [
    "function this prevents replacement by a block",
    "export function run(consume: (value: unknown) => void) { (function () { consume(this); })(); }",
    [],
  ],
  [
    "function arguments prevent replacement by a block",
    "export function run(consume: (value: unknown) => void) { (function () { consume(arguments); })(); }",
    [],
  ],
  [
    "a named IIFE can refer to its own function binding",
    "export function run(consume: (value: unknown) => void) { (function named() { consume(named); })(); }",
    [],
  ],
  [
    "IIFE parameters establish bindings",
    "export function run(consume: (answer: number) => void) { ((answer: number) => { consume(answer); })(42); }",
    [],
  ],
  [
    "a directive belongs to its function body",
    'export function run(consume: () => void) { (function () { "use strict"; consume(); })(); }',
    [],
  ],
  [
    "a direct eval retains the function environment",
    'export function run(consume: () => void) { (() => { eval("var injected = 1"); consume(); })(); }',
    [],
  ],
  [
    "an IIFE used as a value is outside the scoping rule",
    "declare function consume(answer: number): void; export const answer = (() => { const value = 42; consume(value); })();",
    [],
  ],
  [
    "the core rule owns else followed by if",
    "export function run(left: boolean, right: boolean, consume: () => void, recover: () => void) { if (left) { consume(); } else { if (right) { recover(); } } }",
    [ELSE_IF],
    "export function run(left: boolean, right: boolean, consume: () => void, recover: () => void) { if (left) { consume(); } else if (right) { recover(); } }",
  ],
  [
    "the existing exit rule owns an inner else after return",
    "export function run(left: boolean, right: boolean, consume: () => void) { if (left) { if (right) { return; } else { consume(); } } }",
    [USELESS_ELSE],
  ],
];

function linter(factory: ConfigFactory, typed: boolean, fix = false): ESLint {
  const config = factory({
    tsconfigRootDir: FIXTURE_ROOT,
    projectService: typed,
  }).map((entry) => ({
    ...entry,
    rules: Object.fromEntries(
      Object.entries(entry.rules ?? {}).filter(([id]) => SELECTED_RULES.has(id)),
    ),
  }));
  return new ESLint({
    cwd: FIXTURE_ROOT,
    overrideConfigFile: true,
    overrideConfig: config,
    fix,
  });
}

describe("upstream Unicorn redundancy warnings", () => {
  const factory = createConfig as ConfigFactory;
  const eslint = linter(factory, true);
  const fixer = linter(factory, true, true);

  it.each(REVIEW_CASES)("%s", async (_name, code, expected, fixed) => {
    const [result] = await eslint.lintText(code, {
      filePath: "typed-concision-probe.ts",
    });
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(expected);
    if (fixed !== undefined) {
      const [first] = await fixer.lintText(code, {
        filePath: "typed-concision-probe.ts",
      });
      expect(first?.output).toBe(fixed);
      expect(first?.messages).toEqual([]);
      const [second] = await fixer.lintText(fixed, {
        filePath: "typed-concision-probe.ts",
      });
      expect(second?.output).toBeUndefined();
      expect(second?.messages).toEqual([]);
    }
  });

  it.each(CONFIG_FACTORIES)(
    "%s enables both rules as warnings in the shipped configuration",
    async (_name, configFactory) => {
      const eslint = new ESLint({
        cwd: FIXTURE_ROOT,
        overrideConfigFile: true,
        overrideConfig: configFactory({ tsconfigRootDir: FIXTURE_ROOT }),
      });
      const configured = (await eslint.calculateConfigForFile(
        "typed-concision-probe.ts",
      )) as Linter.Config;
      expect(configured.rules?.[NESTED_IF]).toEqual([1]);
      expect(configured.rules?.[SCOPING_IIFE]).toEqual([1]);
    },
  );

  it("keeps both syntax warnings when type services are unavailable", async () => {
    const eslint = linter(factory, false);
    const [result] = await eslint.lintText(
      "if (left) { if (right) { consume(); } } (() => { const answer = 42; consume(answer); })();",
      { filePath: "typed-concision-probe.ts" },
    );
    expect(result?.fatalErrorCount).toBe(0);
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual([
      NESTED_IF,
      SCOPING_IIFE,
    ]);
    expect(result?.messages.map(({ severity }) => severity)).toEqual([1, 1]);
  });

  it("supports a separate exact suppression for each advisory", async () => {
    const [result] = await eslint.lintText(
      "declare const left: boolean; declare const right: boolean; declare function consume(value?: number): void;\n// eslint-disable-next-line unicorn/no-lonely-if -- keep distinct documented guards\nif (left) { if (right) { consume(); } }\n// eslint-disable-next-line unicorn/prefer-block-statement-over-iife -- keep this local function boundary\n(() => { const answer = 42; consume(answer); })();",
      { filePath: "typed-concision-probe.ts" },
    );
    expect(result?.messages).toEqual([]);
    expect(result?.suppressedMessages.map(({ ruleId }) => ruleId)).toEqual([
      NESTED_IF,
      SCOPING_IIFE,
    ]);
  });
});
