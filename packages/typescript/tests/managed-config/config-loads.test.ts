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
  "src/web-adapters.jsx": 'function Label(props) { return <label {...props} />; } const field = <Trigger render={<Button role="combobox" aria-expanded={open} />} />;\n',
  "src/web-obsolete.jsx": '<img alt="" importance="high" />\n',
  "src/web-markup.jsx": [
    '<div><img src="/image.png" /><iframe src="https://example.com" />',
    '<button aria-hidden="true">Close</button><a href="/next" tabIndex={1}>Next</a>',
    '<link rel="preload" as="font" href="/font.woff2" />',
    '<img src="/hero.png" alt="View" loading="lazy" fetchPriority="high" />',
    '<form><input type="password" name="password" onPaste={event => event.preventDefault()} /></form></div>;',
  ].join("\n"),
  "src/web-markup-valid.jsx": [
    '<div><img src="/image.png" alt="View" /><iframe src="https://example.com" title="Help" />',
    '<dialog><input autoFocus aria-label="Name" /></dialog>',
    '<link rel="preload" as="font" href="/font.woff2" crossOrigin="anonymous" />',
    '<img src="/hero.png" alt="View" loading="eager" fetchPriority="high" /></div>;',
  ].join("\n"),
  "src/message-origin.js":
    'window.addEventListener("message", event => event.origin.startsWith("https://trusted.example"));\n',
  "src/promise-return.ts": "declare function load(): Promise<number>;\nexport function forward(): Promise<number> {\n  return load();\n}\n",
  "src/promise-return.tsx": "declare function load(): Promise<number>;\nexport function forward(): Promise<number> {\n  return load();\n}\n",
  "src/anonymous-default.ts": "export default (value: number): number => value * 2;\n",
  "src/named-default.ts": "export default function double(value: number): number {\n  return value * 2;\n}\n",
  "src/mixed-condition.ts": 'export function display(value: number | string): string {\n  return value ? String(value) : "none";\n}\n',
  "src/nullable-conditions.ts": [
    "export function summary(name: string | undefined, count: number | undefined, done: boolean | undefined): string {",
    '  if (!name || !count) return "";',
    "  return done ? name : `${name} (${String(count)})`;",
    "}",
    "",
  ].join("\n"),
  "src/promise-statics.js": "export const value = new Promise.resolve(1);\n",
  "src/promise-statics-valid.js": "export const value = Promise.resolve(1);\n",
  "src/live-binding.ts": "export let count = 0;\nexport function increment(): void {\n  count += 1;\n}\n",
  "src/constant-binding.ts": "export const count = 0;\n",
  "src/self-import.ts": 'import * as self from "./self-import.js";\nexport const value = 1;\nexport const doubled = self.value * 2;\n',
  "src/sibling-import.ts": 'import { value } from "./self-import.js";\nexport const tripled = value * 3;\n',
  "src/promise-finally.tsx": [
    "export function settle(): Promise<number> {",
    "  return Promise.resolve(1).finally(() => {",
    "    return 2;",
    "  });",
    "}",
    "",
  ].join("\n"),
  "src/promise-finally-valid.tsx": [
    "export function settle(ready: boolean, reset: () => void): Promise<number> {",
    "  return Promise.resolve(1).finally(() => {",
    "    if (ready) return;",
    "    reset();",
    "  });",
    "}",
    "",
  ].join("\n"),
  "src/promise-params.js": "export const value = Promise.resolve(1, 2).then();\n",
  "src/promise-params-valid.js": "export const value = Promise.resolve(1).then((result) => result);\n",
  "src/modern-constructs.ts": "export const combined = Object.assign({}, { active: true });\nexport const power = Math.pow(2, 3);\nexport const number = parseInt(\"111110111\", 2);\nexport const object = new Object();\nexport const array = new Array(\"entry\");\nexport const population = 1000000;\nexport function update(parent: Element, child: Element, replacement: Element): void {\n  parent.appendChild(child);\n  parent.removeChild(child);\n  parent.replaceChild(replacement, child);\n}\n",
  "src/modern-constructs-valid.ts": "export const combined = { ...{ active: true } };\nexport const power = 2 ** 3;\nexport const number = 0b1_1111_0111;\nexport const object = {};\nexport const array = [\"entry\"];\nexport const population = 1_000_000;\nexport function update(parent: Element, child: Element, replacement: Element): void {\n  parent.append(child);\n  child.remove();\n  child.replaceWith(replacement);\n}\n",
  "src/new-upstream-rules.ts": "class Session { constructor(readonly id: string) {} }\nexport const session: Session = { id: \"guest\" };\nexport function run(input: string, verbose = false, options = { retries: 1 }) { return { input, verbose, options }; }\nexport function combine(enabled: boolean, overrides: Record<string, string>) { return { ...enabled && overrides }; }\n",
  "src/new-upstream-rules-valid.ts": "class Session { constructor(readonly id: string) {} }\nexport const session: Session = new Session(\"guest\");\nexport function run(input: string, { verbose = false, retries = 1 } = {}) { return { input, verbose, retries }; }\nexport function combine(enabled: boolean, overrides: Record<string, string>) { return { ...(enabled && overrides) }; }\n",
  "src/regexp-match.js": "export const match = \"abc\".match(/b/);\n",
  "src/regexp-exec.js": "export const match = /b/.exec(\"abc\");\n",
  "src/async-cleanup.ts": "export async function settle(cleanup: () => Promise<void>): Promise<void> { await Promise.resolve().finally(async () => { await cleanup(); }); }\n",

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
    env: { HOME: process.env["HOME"], PATH: process.env["PATH"], OXLINT_TSGOLINT_PATH: join(MODULES, ".bin/tsgolint") },
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
  it("runs the newly available native and upstream rules without rejecting valid boundaries", () => {
    const expected = ["typescript(no-unsafe-class-instance-assignment)", "unicorn-js(prefer-options-parameter)", "unicorn-js(require-spread-parentheses)"];
    expect(codesOf("src/new-upstream-rules.ts")).toEqual(expect.arrayContaining(expected));
    expect(codesOf("src/new-upstream-rules-valid.ts").filter(code => expected.includes(code))).toEqual([]);
    expect(codesOf("src/regexp-match.js")).toContain("unicorn-js(prefer-regexp-exec)");
    expect(codesOf("src/regexp-exec.js")).not.toContain("unicorn-js(prefer-regexp-exec)");
    expect(codesOf("src/async-cleanup.ts")).not.toContain("unicorn-js(no-async-promise-finally)");
  });

  it("runs native modern-construct warnings and accepts their alternatives", () => {
    const expected = [
      "eslint(prefer-object-spread)",
      "eslint(prefer-exponentiation-operator)",
      "eslint(prefer-numeric-literals)",
      "eslint(no-object-constructor)",
      "unicorn(no-new-array)",
      "unicorn(numeric-separators-style)",
      "unicorn(prefer-dom-node-append)",
      "unicorn(prefer-dom-node-remove)",
      "unicorn(prefer-modern-dom-apis)",
    ];
    expect(codesOf("src/modern-constructs.ts")).toEqual(expect.arrayContaining(expected));
    expect(codesOf("src/modern-constructs-valid.ts").filter(code => expected.includes(code))).toEqual([]);
  });

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
      "@sarj(directive-no-use)",
      "@sarj(directive-require-description)",
      "unicorn(no-abusive-eslint-disable)",
    ]));
    expect(codesOf("src/directives.ts")).toEqual(expect.arrayContaining([
      "@sarj(directive-no-restricted-disable)",
      "@sarj(directive-no-use)",
      "@sarj(directive-require-description)",
    ]));
  });

  it("applies the ignore patterns the consumer config spreads", () => {
    expect(codesOf("dist/built.ts")).toEqual([]);
  });

  it("preserves unresolved label adapters and render-prop roles", () => {
    expect(codesOf("src/web-adapters.jsx").filter(code => code.startsWith("jsx-a11y("))).toEqual([]);
  });

  it("covers the obsolete attribute still accepted by the native upstream rule", () => {
    expect(codesOf("src/web-obsolete.jsx")).not.toContain("react(no-unknown-property)");
    expect(codesOf("src/web-obsolete.jsx")).toContain("@sarj(no-invalid-web-resource-hints)");
  });

  it("checks native accessibility and web guidance through the shipped preset", () => {
    expect(codesOf("src/web-markup.jsx")).toEqual(
      expect.arrayContaining([
        "jsx-a11y(alt-text)",
        "jsx-a11y(iframe-has-title)",
        "jsx-a11y(no-aria-hidden-on-focusable)",
        "jsx-a11y(tabindex-no-positive)",
        "@sarj(no-invalid-web-resource-hints)",
        "@sarj(no-password-get-form)",
        "@sarj(no-blocked-input-paste)",
      ]),
    );
    expect(codesOf("src/message-origin.js")).toContain("@sarj(no-message-origin-string-matching)");
    expect(
      codesOf("src/web-markup-valid.jsx").filter(
        (code) => code.startsWith("jsx-a11y(") || code === "@sarj(no-invalid-web-resource-hints)",
      ),
    ).toEqual([]);
  });

  it("requires async on promise-returning functions outside JSX files", () => {
    expect(codesOf("src/promise-return.ts")).toContain("typescript(promise-function-async)");
    expect(codesOf("src/promise-return.tsx")).not.toContain("typescript(promise-function-async)");
  });

  it("rejects an anonymous default export and accepts a named one", () => {
    expect(codesOf("src/anonymous-default.ts")).toContain("import(no-anonymous-default-export)");
    expect(codesOf("src/named-default.ts")).not.toContain("import(no-anonymous-default-export)");
  });

  it("reports mixed-type union conditions and allows nullable primitive conditions", () => {
    expect(codesOf("src/mixed-condition.ts")).toContain("typescript(strict-boolean-expressions)");
    expect(codesOf("src/nullable-conditions.ts")).not.toContain("typescript(strict-boolean-expressions)");
  });

  it("reports new on Promise static methods in JavaScript the type check skips", () => {
    expect(codesOf("src/promise-statics.js")).toContain("promise(no-new-statics)");
    expect(codesOf("src/promise-statics-valid.js")).not.toContain("promise(no-new-statics)");
  });

  it("rejects a reassignable export binding and accepts a constant one", () => {
    expect(codesOf("src/live-binding.ts")).toContain("import(no-mutable-exports)");
    expect(codesOf("src/constant-binding.ts")).not.toContain("import(no-mutable-exports)");
  });

  it("rejects a module that imports itself and accepts a sibling import", () => {
    expect(codesOf("src/self-import.ts")).toContain("import(no-self-import)");
    expect(codesOf("src/sibling-import.ts")).not.toContain("import(no-self-import)");
  });

  it("reports values returned from finally callbacks where strict-void-return is off", () => {
    expect(codesOf("src/promise-finally.tsx")).toContain("promise(no-return-in-finally)");
    expect(codesOf("src/promise-finally-valid.tsx")).not.toContain("promise(no-return-in-finally)");
  });

  it("reports Promise method arity in JavaScript the type check skips", () => {
    expect(codesOf("src/promise-params.js")).toContain("promise(valid-params)");
    expect(codesOf("src/promise-params-valid.js")).not.toContain("promise(valid-params)");
  });
});
