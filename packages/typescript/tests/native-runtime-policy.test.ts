import { resolve } from "node:path";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig as createStrictConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_DIR = resolve(import.meta.dirname, "fixtures/runs");
type ConfigFactory = (options: { projectService?: boolean; tsconfigRootDir: string }) => Linter.Config[];
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createStrictConfig],
  ["application", createApplicationConfig],
];
const OWNED_RULES = new Set([
  "no-promise-executor-return",
  "no-self-compare",
  "no-template-curly-in-string",
  "no-unmodified-loop-condition",
  "regexp/no-contradiction-with-assertion",
  "regexp/no-useless-assertions",
  "no-caller",
  "no-restricted-properties",
  "no-eval",
  "no-iterator",
  "no-proto",
  "no-restricted-syntax",
  "@typescript-eslint/no-for-in-array",
]);
const ADVISORY_CASES = [
  ["no-promise-executor-return", "new Promise(() => { return 7; });", "Promise.resolve(7);"],
  [
    "no-unmodified-loop-condition",
    "for (let index = 0; index < 3;) { consume(index); }",
    "for (let index = 0; index < 3; index += 1) { consume(index); }",
  ],
  [
    "no-template-curly-in-string",
    `const greeting = "Hello \${name}";`,
    `const greeting = \`Hello \${name}\`;`,
  ],
  ["no-self-compare", "if (left === left) consume();", "if (left === right) consume();"],
  [
    "regexp/no-contradiction-with-assertion",
    "const pattern = /(?=x)(?:x|y)/;",
    "const pattern = /x/;",
  ],
  ["regexp/no-useless-assertions", "const pattern = /id\\b-/;", "const pattern = /id-/;"],
] as const;
const BANNED_CASES = [
  ["no-eval", 'eval("input");'],
  ["no-eval", '(0, eval)("input");'],
  ["no-eval", 'globalThis.eval("input");'],
  ["no-eval", 'const execute = eval; execute("input");'],
  ["no-restricted-properties", "function inspect() { return arguments.callee; }"],
  ["no-restricted-properties", "function inspect() { return arguments.caller; }"],
  ["no-restricted-properties", 'function inspect() { return arguments["caller"]; }'],
  ["no-restricted-properties", 'function inspect() { return arguments["callee"]; }'],
  ["no-restricted-properties", "function inspect() { return arguments?.callee; }"],
  ["no-restricted-properties", "function inspect() { return arguments[`caller`]; }"],
  ["no-restricted-properties", "function inspect() { const { callee } = arguments; return callee; }"],
  ["no-restricted-properties", "function inspect() { let caller; ({ caller } = arguments); return caller; }"],
  ["no-proto", "const prototype = record.__proto__;"],
  ["no-proto", 'record["__proto__"] = prototype;'],
  ["no-proto", "const prototype = record?.__proto__;"],
  ["no-iterator", "collection.__iterator__();"],
  ["no-iterator", 'collection["__iterator__"]();'],
  ["no-iterator", "collection?.__iterator__?.();"],
  ["no-restricted-syntax", "for (const key in record) consume(key);"],
  ["no-restricted-syntax", 'for (const index in ["a", "b"]) consume(index);'],
  ["no-restricted-syntax", "for (key in record) consume(key);"],
] as const;

function focusedConfig(createConfig: ConfigFactory, typed = false): Linter.Config[] {
  return createConfig({ tsconfigRootDir: FIXTURE_DIR, projectService: typed }).map(entry => entry.rules ? ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => OWNED_RULES.has(id))),
  }) : entry);
}

function linter(createConfig: ConfigFactory, typed = false, fix = false): ESLint {
  return new ESLint({
    cwd: FIXTURE_DIR,
    overrideConfigFile: true,
    overrideConfig: focusedConfig(createConfig, typed),
    fix,
  });
}

async function messages(eslint: ESLint, source: string, filePath = "runtime-policy.ts"): Promise<Linter.LintMessage[]> {
  const [result] = await eslint.lintText(source, { filePath });
  expect(result?.fatalErrorCount).toBe(0);
  return result?.messages ?? [];
}

describe.each(CONFIG_FACTORIES)("%s native runtime policy", (_name, createConfig) => {
  const eslint = linter(createConfig);

  it.each(ADVISORY_CASES)("warns on %s and accepts the corresponding alternative", async (ruleId, bad, good) => {
    expect((await messages(eslint, bad)).map(({ ruleId: id, severity }) => ({ id, severity }))).toEqual([
      { id: ruleId, severity: 1 },
    ]);
    expect(await messages(eslint, good)).toEqual([]);
  });

  it.each(BANNED_CASES)("rejects %s through its native owner: %s", async (ruleId, source) => {
    expect((await messages(eslint, source)).map(({ ruleId: id, severity }) => ({ id, severity }))).toEqual([
      { id: ruleId, severity: 2 },
    ]);
  });

  it.each(["runtime-policy.js", "runtime-policy.mjs", "runtime-policy.cjs", "vite.config.ts", "runtime-policy.test.ts"])(
    "retains source restrictions and warning levels in %s",
    async filePath => {
      const source = 'for (const key in record) consume(key);\nnew Promise(() => { return 7; });';
      expect((await messages(eslint, source, filePath)).map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([
        { ruleId: "no-restricted-syntax", severity: 2 },
        { ruleId: "no-promise-executor-return", severity: 1 },
      ]);
    },
  );

  it.each([
    'const source = "eval(input); arguments.callee; __proto__; __iterator__; for-in";',
    '// eval(input); arguments.callee; record.__proto__; collection.__iterator__();\n',
    'const metadata = { caller: "owner", callee: "worker" }; consume(metadata.caller, metadata.callee);',
    'const metadata = JSON.parse(\'{"__proto__":1,"__iterator__":2}\');',
    "const record = { __proto__: null };",
    "const prototype = Object.getPrototypeOf(record);",
    "const iterator = collection[Symbol.iterator]();",
    'const service = { eval(value) { return value; } }; service.eval("data");',
    "for (const key of Object.keys(record)) consume(key);",
    "for (const [key, value] of Object.entries(record)) consume(key, value);",
    "for await (const item of stream) consume(item);",
    'if ("key" in record) consume(record);',
    'if (typeof input === "undefined") consume(input);',
    "type Input = typeof input;",
  ])("preserves non-target syntax and data contracts: %s", async source => {
    expect(await messages(eslint, source)).toEqual([]);
  });

  it("retains existing runtime typeof restrictions", async () => {
    expect((await messages(eslint, 'if (typeof input === "string") consume(input);')).map(({ ruleId, severity }) => ({ ruleId, severity })))
      .toEqual([{ ruleId: "no-restricted-syntax", severity: 2 }]);
  });

  it("reports each nested for-in loop once", async () => {
    const source = "for (const key in record) { for (const index in values) consume(key, index); }";
    expect((await messages(eslint, source)).map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([
      { ruleId: "no-restricted-syntax", severity: 2 },
      { ruleId: "no-restricted-syntax", severity: 2 },
    ]);
  });

  it("replaces typed array-only ownership without duplicate findings", async () => {
    const typed = linter(createConfig, true);
    const source = "const values: number[] = [1, 2]; for (const key in values) consume(key);";
    expect((await messages(typed, source, "example.ts")).map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([
      { ruleId: "no-restricted-syntax", severity: 2 },
    ]);
    const config = await typed.calculateConfigForFile("example.ts") as Linter.Config;
    expect(config.rules?.["@typescript-eslint/no-for-in-array"]).toEqual([0]);
  });

  it("honors an exact explained exception without disabling other rules", async () => {
    const source = "// eslint-disable-next-line no-restricted-syntax -- This fixture deliberately exercises inherited-key enumeration.\nfor (const key in record) consume(key);\neval(input);";
    expect((await messages(eslint, source)).map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([
      { ruleId: "no-eval", severity: 2 },
    ]);
  });

  it("keeps generated-source exclusions", async () => {
    expect(await eslint.lintText("eval(input);", { filePath: "generated/runtime.ts", warnIgnored: false })).toEqual([]);
  });

  it("retains native parse failures", async () => {
    const [result] = await eslint.lintText("for (const key in", { filePath: "runtime-policy.ts" });
    expect(result?.fatalErrorCount).toBe(1);
  });

  it.each([
    ["for (const key in record) consume(key);", "no-restricted-syntax", 2],
    ["nextValue() === nextValue();", "no-self-compare", 1],
    ["new Promise(resolve => resolve(7));", "no-promise-executor-return", 1],
  ] as const)("does not rewrite intent-dependent source: %s", async (source, ruleId, severity) => {
    const [result] = await linter(createConfig, false, true).lintText(source, { filePath: "runtime-policy.ts" });
    expect(result?.output).toBeUndefined();
    expect(result?.messages.map(({ ruleId: id, severity: level }) => ({ id, level }))).toEqual([
      { id: ruleId, level: severity },
    ]);
  });
});
