import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { afterAll, beforeAll, expect, it } from "vitest";

import { ALL_TEST_FRAMEWORKS, createConfig, jsPlugins } from "./managed-config/managed-config.js";

const PACKAGE = fileURLToPath(new URL("../", import.meta.url));
const PEERS = JSON.parse(
  await readFile(
    new URL("../../standards/src/sarj_standards/configs/typescript.peers.json", import.meta.url),
    "utf8",
  ),
) as { peers: Record<string, string> };
const MANAGED = createConfig({ testFrameworks: ALL_TEST_FRAMEWORKS });
const ROOT = await mkdtemp(join(tmpdir(), "standalone-upstream-"));
const GUARD = `import {registerHooks} from "node:module";
registerHooks({resolve(specifier, context, next) {
  if (specifier === "eslint" || specifier.startsWith("eslint/")) throw new Error("ESLint runtime import: " + specifier);
  return next(specifier, context);
}});`;

function command(executable: string, args: readonly string[], cwd = ROOT): string {
  const result = spawnSync(executable, args, { cwd, encoding: "utf8", timeout: 60_000 });
  if (result.error) throw result.error;
  expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
  return result.stdout;
}

beforeAll(async () => {
  const packed = JSON.parse(
    command("npm", ["pack", "--ignore-scripts", "--json", "--pack-destination", ROOT], PACKAGE),
  ) as Record<string, { filename: string }>;
  await writeFile(
    join(ROOT, "package.json"),
    '{"name":"standalone-upstream-test","private":true,"type":"module"}\n',
  );
  command("npm", [
    "install",
    "--ignore-scripts",
    "--no-audit",
    "--no-fund",
    ...Object.entries(PEERS.peers).map(([name, version]) =>
      name === "@sarj/eslint-plugin"
        ? join(ROOT, Object.values(packed)[0]!.filename)
        : `${name}@${version}`,
    ),
  ]);
  await writeFile(join(ROOT, "guard.mjs"), GUARD);
}, 60_000);

afterAll(async () => {
  await rm(ROOT, { recursive: true, force: true });
});

it("freshly installs and loads the selected upstream rules with no ESLint package or imports", async () => {
  const lock = JSON.parse(await readFile(join(ROOT, "package-lock.json"), "utf8")) as {
    packages: Record<string, unknown>;
  };
  expect(
    Object.keys(lock.packages).filter((path) => /(?:^|\/)node_modules\/eslint$/u.test(path)),
  ).toEqual([]);
  await writeFile(
    join(ROOT, "probe.mjs"),
    `${GUARD}
const loaded = {};
for (const {name,specifier} of ${JSON.stringify(jsPlugins(MANAGED))}) {
  const plugin = (await import(specifier)).default;
  loaded[name] = Object.keys(plugin.rules).sort();
}
await import("oxlint-plugin-react-doctor");
await import("oxlint-plugin-react-doctor/core");
await import("@sarj/eslint-plugin");
console.log(JSON.stringify(loaded));`,
  );
  const loaded = JSON.parse(command(process.execPath, ["probe.mjs"])) as {
    [alias: string]: string[];
  };
  const configured = new Set(
    [MANAGED.rules, ...(MANAGED.overrides ?? []).map((override) => override.rules)].flatMap(
      (rules) => Object.keys(rules ?? {}),
    ),
  );
  const selected = (alias: string): string[] =>
    [...configured]
      .filter((id) => id.startsWith(`${alias}/`))
      .map((id) => id.slice(alias.length + 1))
      .sort();
  for (const { name, specifier } of jsPlugins(MANAGED)) {
    if (specifier.startsWith("@sarj/eslint-plugin/")) expect(loaded[name]).toEqual(selected(name));
    else expect(loaded[name]).toEqual(expect.arrayContaining(selected(name)));
  }
});

it("matches pinned upstream Oxlint 1.91 findings and fixes after a fresh ESLint-free install", async () => {
  await writeFile(
    join(ROOT, "oxlint.config.mjs"),
    `import "./guard.mjs";
export default {
  categories:{correctness:"off"},
  jsPlugins:[{name:"unicorn-js",specifier:"@sarj/eslint-plugin/unicorn"},{name:"jsdoc-js",specifier:"@sarj/eslint-plugin/jsdoc"}],
  rules:{"unicorn-js/prefer-type-error":"error","jsdoc-js/no-restricted-syntax":["error",{contexts:[{context:"FunctionDeclaration",message:"No implementation JSDoc"}]}]}
};`,
  );
  await writeFile(
    join(ROOT, "invalid.ts"),
    '/** implementation */\nexport function fail(value: unknown) { if (typeof value !== "string") throw new Error("Expected a string"); }\n',
  );
  const lint = spawnSync(
    process.execPath,
    ["node_modules/oxlint/bin/oxlint", "-c", "oxlint.config.mjs", "--format=json", "invalid.ts"],
    { cwd: ROOT, encoding: "utf8", timeout: 30_000 },
  );
  expect(lint.error).toBeUndefined();
  expect(lint.status, lint.stderr).toBe(1);
  const output = JSON.parse(lint.stdout) as { diagnostics: { code: string }[] };
  expect(output.diagnostics).toEqual([
    {
      message: "No implementation JSDoc",
      code: "jsdoc-js(no-restricted-syntax)",
      severity: "error",
      filename: "invalid.ts",
      labels: [{ span: { offset: 0, length: 21, line: 1, column: 1 } }],
    },
    {
      message: "`new Error()` is too unspecific for a type check. Use `new TypeError()` instead.",
      code: "unicorn-js(prefer-type-error)",
      severity: "error",
      filename: "invalid.ts",
      labels: [{ span: { offset: 102, length: 5, line: 2, column: 81 } }],
    },
  ]);
  expect(output.diagnostics.map((diagnostic) => diagnostic.code).sort()).toEqual([
    "jsdoc-js(no-restricted-syntax)",
    "unicorn-js(prefer-type-error)",
  ]);
  const fixed = spawnSync(
    process.execPath,
    ["node_modules/oxlint/bin/oxlint", "-c", "oxlint.config.mjs", "--fix", "invalid.ts"],
    { cwd: ROOT, encoding: "utf8", timeout: 30_000 },
  );
  expect(fixed.error).toBeUndefined();
  expect(fixed.status, `${fixed.stdout}\n${fixed.stderr}`).toBe(1);
  expect(await readFile(join(ROOT, "invalid.ts"), "utf8")).toBe(
    '/** implementation */\nexport function fail(value: unknown) { if (typeof value !== "string") throw new TypeError("Expected a string"); }\n',
  );
});
