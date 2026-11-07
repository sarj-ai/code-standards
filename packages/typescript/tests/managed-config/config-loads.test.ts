// oxlint.strict.mts synced next to an oxlint.config.mts that extends it, plugins

import { spawnSync } from "node:child_process";
import { copyFile, mkdir, mkdtemp, readdir, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, describe, expect, it } from "vitest";

import { CONFIGS_DIR } from "./managed-config.js";

const PACKAGE_DIR = fileURLToPath(new URL("../../", import.meta.url));
const MODULES = join(PACKAGE_DIR, "node_modules");

const FILES: Readonly<Record<string, string>> = {
  "package.json": `${JSON.stringify({ name: "consumer", private: true, type: "module" })}\n`,
  "tsconfig.json": `${JSON.stringify({
    compilerOptions: { strict: true, target: "es2024", module: "nodenext", noEmit: true, skipLibCheck: true, types: [] },
    include: ["src", "tests", "vite.config.ts"],
  })}\n`,
  "oxlint.config.mts": [
    'import { defineConfig } from "oxlint";',
    'import { createConfig, ignorePatterns } from "./oxlint.strict.mts";',
    'const managed = createConfig({ testFrameworks: ["vitest", "bun", "node", "testing-library", "playwright"] });',
    "export default defineConfig({",
    "  extends: [managed],",
    "  settings: managed.settings,",
    "  ignorePatterns: [...ignorePatterns],",
    "  overrides: [],",
    "});",
    "",
  ].join("\n"),
  "src/sample.ts": [
    "async function load(): Promise<number> {",
    "  return 1;",
    "}",
    "",
    "export async function run(items: readonly number[]): Promise<number> {",
    "  let total = 0;",
    "  for (const item of items) total += await load() + item;",
    "  load();",
    "  return total;",
    "}",
    "",
    "export function keys(record: Readonly<Record<string, number>>): string[] {",
    "  const result: string[] = [];",
    "  for (const key in record) result.push(key);",
    "  return result;",
    "}",
    "",
    'export const count: number = "one";',
    "export enum Color { Red }",
    "",
  ].join("\n"),
  "tests/sample.test.ts": [
    "export async function run(items: readonly number[], load: () => Promise<number>): Promise<number> {",
    "  let total = 0;",
    "  for (const item of items) total += await load() + item;",
    "  return total;",
    "}",
    "",
  ].join("\n"),
  "tests/sample.bun.test.ts": [
    'test("is empty", () => {',
    "  expect([].at(0)).toEqual(undefined);",
    "});",
    "",
  ].join("\n"),
  "vite.config.ts": [
    "async function load(): Promise<number> {",
    "  return 1;",
    "}",
    "",
    "load();",
    "export default {};",
    "",
  ].join("\n"),
  "dist/built.ts": "export enum Built { Yes }\n",
  "src/worker-configuration.d.ts": "/* eslint-disable */\nexport declare const value: any;\n",
  "src/directives.ts": "// oxlint-disable-next-line no-console\nconsole.log(1);\n/* oxlint-disable no-console -- the CLI prints its report */\nconsole.log(2);\n",
};

interface Diagnostic {
  readonly code?: string;
  readonly message: string;
  readonly filename: string;
}

let consumer = "";
let codes: ReadonlyMap<string, ReadonlySet<string>> = new Map();
let problems: readonly string[] = [];

beforeAll(async () => {
  consumer = await mkdtemp(join(tmpdir(), "sarj-managed-oxlint-"));
  for (const [path, text] of Object.entries(FILES)) {
    await mkdir(dirname(join(consumer, path)), { recursive: true });
    await writeFile(join(consumer, path), text);
  }
  await copyFile(new URL("oxlint.strict.mts", CONFIGS_DIR), join(consumer, "oxlint.strict.mts"));
  await mkdir(join(consumer, "node_modules/@sarj"), { recursive: true });
  for (const entry of await readdir(MODULES)) {
    if (entry !== "@sarj" && entry !== ".bin") await symlink(join(MODULES, entry), join(consumer, "node_modules", entry));
  }
  const installed = join(consumer, "node_modules/@sarj/eslint-plugin");
  await mkdir(installed);
  for (const entry of ["package.json", "dist"]) await symlink(join(PACKAGE_DIR, entry), join(installed, entry));

  const result = spawnSync(join(MODULES, ".bin/oxlint"), ["-f", "json"], {
    cwd: consumer,
    encoding: "utf8",
    env: { HOME: process.env["HOME"], PATH: process.env["PATH"], OXLINT_TSGOLINT_PATH: join(MODULES, ".bin/tsrs-lint") },
    maxBuffer: 1 << 26,
  });
  if ((result.status !== 0 && result.status !== 1) || !result.stdout.startsWith("{")) {
    throw new Error(`oxlint exited ${String(result.status)}\n${result.stderr}${result.stdout}`);
  }
  const { diagnostics } = JSON.parse(result.stdout) as { diagnostics: readonly Diagnostic[] };
  const byFile = new Map<string, Set<string>>();
  for (const { code, filename } of diagnostics) {
    if (code === undefined || code === "") continue;
    byFile.set(filename, (byFile.get(filename) ?? new Set()).add(code));
  }
  codes = byFile;
  problems = diagnostics.filter(({ code }) => code === undefined || code === "").map(({ message }) => message.split("\n")[0] ?? "");
}, 120_000);

afterAll(async () => {
  await rm(consumer, { recursive: true, force: true });
});

const codesOf = (path: string): readonly string[] => [...(codes.get(path) ?? [])].toSorted();

describe("the managed Oxlint config in a consumer", () => {
  it("loads every plugin without a crash", () => {
    expect(problems).toEqual([]);
  });

  it("runs native, JS plugin, @sarj and type-aware rules and the type check on source", () => {
    expect(codesOf("src/sample.ts")).toEqual(expect.arrayContaining([
      "@sarj(no-enum)",
      "eslint(no-await-in-loop)",
      "eslint-js(no-restricted-syntax)",
      "typescript(TS2322)",
      "typescript(no-floating-promises)",
    ]));
  });

  it("applies the test overrides", () => {
    expect(codesOf("tests/sample.test.ts")).not.toContain("eslint(no-await-in-loop)");
    expect(codesOf("tests/sample.bun.test.ts")).toContain("jest(prefer-to-be)");
  });

  it("turns type-aware rules off in syntax-only config files", () => {
    expect(codesOf("vite.config.ts")).not.toContain("typescript(no-floating-promises)");
  });

  it("runs the suppression policy on eslint-* and oxlint-* directives, including on line 1", () => {
    expect(codesOf("src/worker-configuration.d.ts")).toEqual(expect.arrayContaining([
      "@sarj(directive-disable-enable-pair)",
      "@sarj(directive-no-use)",
      "@sarj(directive-require-description)",
      "unicorn(no-abusive-eslint-disable)",
    ]));
    expect(codesOf("src/directives.ts")).toEqual(expect.arrayContaining([
      "@sarj(directive-disable-enable-pair)",
      "@sarj(directive-no-restricted-disable)",
      "@sarj(directive-no-use)",
      "@sarj(directive-require-description)",
    ]));
  });

  it("applies the ignore patterns the consumer config spreads", () => {
    expect(codesOf("dist/built.ts")).toEqual([]);
  });
});
