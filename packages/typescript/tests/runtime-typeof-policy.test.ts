import { resolve } from "node:path";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_DIR = resolve(import.meta.dirname, "fixtures/runs");
const CONFIG_FACTORY = createConfig as unknown as (options: { projectService: boolean }) => Linter.Config[];
const CONFIG = CONFIG_FACTORY({ projectService: false }).map((entry) => ({
  ...entry,
  rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([name]) => name === "no-restricted-syntax")),
}));
const ESLINT = new ESLint({ cwd: FIXTURE_DIR, overrideConfigFile: true, overrideConfig: CONFIG });

async function messages(source: string): Promise<Linter.LintMessage[]> {
  const [result] = await ESLINT.lintText(source, { filePath: "runtime-types.ts" });
  expect(result?.messages.filter(message => message.fatal)).toEqual([]);
  return result?.messages.filter(message => message.ruleId === "no-restricted-syntax") ?? [];
}

describe("runtime typeof policy", () => {
  it.each([
    'if (typeof input === "string") use(input);',
    'const representation = typeof input;',
    'function isText(input: unknown): input is string { return typeof input === "string"; }',
    'function parse(input: unknown) { if (typeof input !== "object") throw new Error(); return input; }',
    'if (typeof window === undefined) use(window);',
    'if (typeof input === "undefined" || typeof input === "string") use(input);',
    'const kind = { type: typeof input };',
  ])("rejects runtime representation checks: %s", async source => {
    const result = await messages(source);
    expect(result.map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([{ ruleId: "no-restricted-syntax", severity: 2 }]);
    expect(result[0]?.message).toContain("runtime typeof");
  });

  it.each([
    'if (typeof window === "undefined") renderServer();',
    'if ("undefined" !== typeof document) renderClient();',
    'if (typeof window != "undefined") renderClient();',
    'if ("undefined" == typeof window) renderServer();',
    'const value = object.typeof;',
    'const missing = typeof globalThis.crypto == "undefined";',
    'type Input = typeof input;',
    'type Item = (typeof items)[number];',
    'const description = "typeof input"; // typeof input\n',
    'const result = InputSchema.safeParse(input);',
  ])("accepts existence checks and type queries: %s", async source => {
    expect(await messages(source)).toEqual([]);
  });
});
