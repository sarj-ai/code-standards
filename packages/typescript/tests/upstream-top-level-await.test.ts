import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";

interface Control {
  name: string;
  source: string;
  expected: number;
}
const controls = JSON.parse(
  readFileSync(
    new URL("./upstream-top-level-await-controls.json", import.meta.url),
    "utf8",
  ),
) as Control[];
const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);

function writeConfig(directory: string) {
  writeFileSync(
    path.join(directory, "oxlint.json"),
    JSON.stringify({
      categories: { correctness: "off" },
      jsPlugins: [
        {
          name: "sarj-unicorn",
          specifier: fileURLToPath(
            import.meta.resolve("@sarj/oxlint-plugin/upstream/unicorn"),
          ),
        },
      ],
      rules: { "sarj-unicorn/prefer-top-level-await": "error" },
    }),
  );
}
function lint(directory: string, flags: string[] = []) {
  return spawnSync(
    process.execPath,
    [engine, "--config", "oxlint.json", "--format=json", ...flags, "."],
    { cwd: directory, encoding: "utf8", timeout: 30_000 },
  );
}

it("retains maintained Unicorn Promise checks and safe Zod schema catch fallbacks", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-top-level-await-"));
  try {
    writeConfig(directory);
    for (const control of controls)
      writeFileSync(path.join(directory, `${control.name}.ts`), control.source);
    const run = lint(directory);
    expect(run).toMatchObject({ status: 1, stderr: "" });
    const diagnostics = (
      JSON.parse(run.stdout) as {
        diagnostics: Array<{ filename: string; code: string }>;
      }
    ).diagnostics;
    expect(
      diagnostics.map((item) => `${item.filename}:${item.code}`).toSorted(),
    ).toEqual(
      controls
        .flatMap((control) =>
          Array.from(
            { length: control.expected },
            () => `${control.name}.ts:sarj-unicorn(prefer-top-level-await)`,
          ),
        )
        .toSorted(),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("applies only the maintained async-call suggestion and reaches a stable clean result", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-await-suggestion-"));
  try {
    writeConfig(directory);
    const file = path.join(directory, "sample.ts");
    writeFileSync(file, "const start=async()=>{await run()};start();");
    expect(lint(directory, ["--fix-suggestions"])).toMatchObject({
      status: 0,
      stderr: "",
    });
    const fixed = readFileSync(file, "utf8");
    expect(fixed).toContain("await start()");
    expect(lint(directory, ["--fix-suggestions"])).toMatchObject({
      status: 0,
      stderr: "",
    });
    expect(readFileSync(file, "utf8")).toBe(fixed);
    const promise = "Promise.resolve(1).catch(()=>0);";
    writeFileSync(file, promise);
    expect(lint(directory, ["--fix"])).toMatchObject({ status: 1, stderr: "" });
    expect(readFileSync(file, "utf8")).toBe(promise);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("selects the licensed rule without duplicate stock diagnostics", async () => {
  const config = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
  });
  expect(config.rules?.["unicorn/prefer-top-level-await"]).toBe("off");
  expect(config.rules?.["sarj-unicorn/prefer-top-level-await"]).toBe("error");
});
