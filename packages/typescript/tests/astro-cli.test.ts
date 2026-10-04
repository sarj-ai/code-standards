import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const cli = path.join(packageRoot, "dist/framework/astro-cli.js");

function withProject(check: (root: string) => void) {
  const root = mkdtempSync(path.join(packageRoot, ".native-astro-cli-"));
  try {
    writeFileSync(
      path.join(root, "package.json"),
      '{"private":true,"type":"module"}',
    );
    writeFileSync(
      path.join(root, "tsconfig.json"),
      '{"compilerOptions":{"jsx":"preserve","allowJs":true,"noEmit":true}}',
    );
    writeFileSync(
      path.join(root, "page.astro"),
      "---\ndebugger;\n---\n<div />",
    );
    check(root);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
}

function configure(root: string, severity: string, ignored = false) {
  writeFileSync(
    path.join(root, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      plugins: ["eslint"],
      rules: { "eslint/no-debugger": severity },
      ...(ignored && { ignorePatterns: ["page.astro"] }),
    }),
  );
}

function run(root: string, flags: string[] = []) {
  return spawnSync(
    process.execPath,
    [
      cli,
      "--config",
      "oxlint.json",
      "--format",
      "json",
      ...flags,
      "--",
      "page.astro",
    ],
    {
      cwd: root,
      encoding: "utf8",
      timeout: 30_000,
    },
  );
}

it("runs genuine mapped Astro diagnostics through the published CLI entry with type-aware selection", () => {
  withProject((root) => {
    configure(root, "error");
    const result = run(root, ["--type-aware"]);
    expect(result).toMatchObject({ status: 1, stderr: "" });
    const report = JSON.parse(result.stdout);
    expect(report["number_of_files"]).toBe(1);
    expect(report).toMatchObject({
      diagnostics: [
        {
          code: "eslint(no-debugger)",
          severity: "error",
          filename: path.join(root, "page.astro"),
          labels: [{ span: { line: 2, column: 1 } }],
        },
      ],
    });
  });
});

it("keeps warning status unless the caller explicitly denies warnings", () => {
  withProject((root) => {
    configure(root, "warn");
    const warning = run(root);
    const denied = run(root, ["--deny-warnings"]);
    expect(warning).toMatchObject({ status: 0, stderr: "" });
    expect(denied).toMatchObject({ status: 1, stderr: "" });
    const report = JSON.parse(warning.stdout);
    expect(report["number_of_files"]).toBe(1);
    expect(report).toMatchObject({
      diagnostics: [{ severity: "warning" }],
    });
    expect(JSON.parse(denied.stdout)).toEqual(report);
  });
});

it("honors original-file ignores and the explicit unmatched selection contract", () => {
  withProject((root) => {
    configure(root, "error", true);
    const rejected = run(root);
    const accepted = run(root, ["--no-error-on-unmatched-pattern"]);
    expect(rejected).toMatchObject({ status: 2, stdout: "" });
    expect(rejected.stderr).toContain("No Astro files matched");
    expect(accepted).toMatchObject({ status: 0, stderr: "" });
    const report = JSON.parse(accepted.stdout);
    expect(report["number_of_files"]).toBe(0);
    expect(report).toMatchObject({
      diagnostics: [],
    });
  });
});

it("rejects unsupported native flags instead of silently changing their meaning", () => {
  withProject((root) => {
    configure(root, "error");
    const result = run(root, ["--unknown-native-option"]);
    expect(result).toMatchObject({ status: 2, stdout: "" });
    expect(result.stderr).toContain("Unknown option");
  });
});

it("reports native type-aware configuration failures instead of hiding them", () => {
  withProject((root) => {
    configure(root, "off");
    writeFileSync(
      path.join(root, "tsconfig.json"),
      '{"compilerOptions":{"jsx":"preserve","allowJs":true}}',
    );
    const result = run(root, ["--type-aware"]);
    expect(result).toMatchObject({ status: 1, stderr: "" });
    const report = JSON.parse(result.stdout);
    expect(report["number_of_files"]).toBe(1);
    expect(report).toMatchObject({
      diagnostics: [
        {
          code: "typescript(tsconfig-error)",
          severity: "error",
        },
      ],
    });
  });
});
