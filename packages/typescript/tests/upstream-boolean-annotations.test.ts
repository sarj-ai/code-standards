import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";

it("distinguishes explicit local boolean property contracts from chained comparisons", () => {
  const directory = mkdtempSync(
    path.join(tmpdir(), "sarj-boolean-properties-"),
  );
  const cases = [
    [
      "boolean",
      "declare const metadata: { supportsApply: boolean }; const mismatch = metadata.supportsApply !== (applyChange !== undefined);",
      0,
    ],
    [
      "parameter",
      "function compare(metadata: { supportsApply: boolean }) { return metadata.supportsApply !== (applyChange !== undefined); }",
      0,
    ],
    [
      "computed",
      "declare const metadata: { supportsApply: boolean }; const mismatch = metadata['supportsApply'] !== (applyChange !== undefined);",
      0,
    ],
    [
      "number",
      "declare const metadata: { supportsApply: number }; const mismatch = metadata.supportsApply !== (applyChange !== undefined);",
      1,
    ],
    [
      "optional",
      "declare const metadata: { supportsApply?: boolean }; const mismatch = metadata.supportsApply !== (applyChange !== undefined);",
      1,
    ],
    [
      "shadowed",
      "declare const metadata: { supportsApply: boolean }; function compare(metadata: { supportsApply: number }) { return metadata.supportsApply !== (applyChange !== undefined); }",
      1,
    ],
    ["range", "const range = 1 < 2 < 3;", 1],
    ["comparison", "const mismatch = (1 < 2) !== (3 < 4);", 0],
  ] as const;
  try {
    writeFileSync(
      path.join(directory, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        jsPlugins: [
          {
            name: "port",
            specifier: fileURLToPath(
              new URL("../src/upstream/unicorn.js", import.meta.url),
            ),
          },
        ],
        rules: { "port/no-chained-comparison": "error" },
      }),
    );
    for (const [name, source] of cases)
      writeFileSync(
        path.join(directory, `${name}.ts`),
        `declare const applyChange: undefined | (() => void); ${source}`,
      );
    const engine = path.join(
      path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
      "bin/oxlint",
    );
    const result = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--format=json", "."],
      { cwd: directory, encoding: "utf8", timeout: 30_000 },
    );
    expect(result).toMatchObject({ status: 1, stderr: "" });
    const report = JSON.parse(result.stdout) as {
      "number_of_files": number;
      diagnostics: Array<{ filename: string; code: string }>;
    };
    expect(report["number_of_files"]).toBe(cases.length);
    expect(
      report.diagnostics
        .map((item) => `${item.filename}:${item.code}`)
        .toSorted(),
    ).toEqual(
      cases
        .flatMap(([name, , count]) =>
          Array.from(
            { length: count },
            () => `${name}.ts:port(no-chained-comparison)`,
          ),
        )
        .toSorted(),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
