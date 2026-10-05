import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";
import { TANSTACK_QUERY_RECOMMENDED_RULES } from "../dist/presets.js";

interface Control {
  rule: string;
  valid: string;
  invalid: string;
}
interface Diagnostic {
  filename: string;
  code?: string;
}
const controls = JSON.parse(
  readFileSync(
    new URL("./upstream-query-controls.json", import.meta.url),
    "utf8",
  ),
) as Control[];
const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const plugin = fileURLToPath(
  new URL("../dist/upstream/query.js", import.meta.url),
);

it("runs all Query rules and same-file semantic controls through the stock worker", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-query-controls-"));
  try {
    const overrides = [];
    for (const [index, control] of controls.entries()) {
      for (const kind of ["valid", "invalid"] as const) {
        const filename = `${kind}-${index}.tsx`;
        writeFileSync(path.join(directory, filename), control[kind]);
        overrides.push({
          files: [filename],
          rules: { [`port/${control.rule}`]: "error" },
        });
      }
    }
    writeConfig(directory, { overrides });
    const run = lint(directory);
    expect(run).toMatchObject({ status: 1, stderr: "" });
    const diagnostics = (
      JSON.parse(run.stdout) as { diagnostics: Diagnostic[] }
    ).diagnostics;
    expect(
      diagnostics.filter(
        (item) => !item.code || item.filename.startsWith("valid-"),
      ),
    ).toEqual([]);
    const missing = controls.flatMap((control, index) =>
      diagnostics.some(
        (item) =>
          item.filename === `invalid-${index}.tsx` &&
          item.code === `port(${control.rule})`,
      )
        ? []
        : [control.rule],
    );
    expect(missing).toEqual([]);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("applies the original Query fixes and reaches a stable clean result", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-query-fixes-"));
  try {
    const fixable = new Set([
      "stable-query-client",
      "infinite-query-property-order",
      "mutation-property-order",
    ]);
    const fixtures = controls.filter(
      (control, index) => index < 7 && fixable.has(control.rule),
    );
    writeConfig(directory, {
      rules: Object.fromEntries(
        [...fixable].map((rule) => [`port/${rule}`, "error"]),
      ),
    });
    for (const fixture of fixtures) {
      writeFileSync(
        path.join(directory, `${fixture.rule}.tsx`),
        `import React from "react";\n${fixture.invalid}`,
      );
    }
    expect(lint(directory, true)).toMatchObject({ status: 0, stderr: "" });
    const changed = fixtures.map((fixture) =>
      readFileSync(path.join(directory, `${fixture.rule}.tsx`), "utf8"),
    );
    expect(lint(directory, true)).toMatchObject({ status: 0, stderr: "" });
    expect(
      fixtures.map((fixture) =>
        readFileSync(path.join(directory, `${fixture.rule}.tsx`), "utf8"),
      ),
    ).toEqual(changed);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("keeps Query opt-in and preserves the original recommended severities and TypeScript scope", async () => {
  const enabled = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
    query: true,
  });
  const defaults = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
  });
  const select = (config: typeof enabled) =>
    config.overrides?.find(
      (override) => "sarj-query/exhaustive-deps" in (override.rules ?? {}),
    );
  expect(select(enabled)).toMatchObject({
    files: ["**/*.{ts,tsx}"],
    rules: TANSTACK_QUERY_RECOMMENDED_RULES,
  });
  expect(select(defaults)?.rules).toEqual(
    Object.fromEntries(
      Object.keys(TANSTACK_QUERY_RECOMMENDED_RULES).map((rule) => [
        rule,
        "off",
      ]),
    ),
  );
  expect(TANSTACK_QUERY_RECOMMENDED_RULES).toMatchObject({
    "sarj-query/no-rest-destructuring": "warn",
  });
});

function writeConfig(directory: string, policy: object) {
  writeFileSync(
    path.join(directory, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      jsPlugins: [{ name: "port", specifier: plugin }],
      ...policy,
    }),
  );
}

function lint(directory: string, fix = false) {
  return spawnSync(
    process.execPath,
    [
      engine,
      "--config",
      "oxlint.json",
      "--format=json",
      ...(fix ? ["--fix"] : []),
      ".",
    ],
    {
      cwd: directory,
      encoding: "utf8",
      timeout: 30_000,
    },
  );
}
