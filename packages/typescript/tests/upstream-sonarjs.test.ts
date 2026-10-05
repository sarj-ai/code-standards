import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";
import { SONARJS_ADDITIONAL_RULES } from "../dist/presets.js";

interface Control {
  name: string;
  rule: string;
  source: string;
  expected: number;
}
const controls = JSON.parse(
  readFileSync(
    new URL("./upstream-sonarjs-controls.json", import.meta.url),
    "utf8",
  ),
) as Control[];
const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);
const plugin = fileURLToPath(
  import.meta.resolve("@sarj/oxlint-plugin/upstream/sonarjs"),
);

function run(root: string, ...options: string[]) {
  return spawnSync(
    process.execPath,
    [engine, "--config", "oxlint.json", "--format=json", ...options, "."],
    {
      cwd: root,
      encoding: "utf8",
      timeout: 30_000,
    },
  );
}

it("preserves all eight Sonar policies with native token, lexical scope and source contracts", () => {
  const root = mkdtempSync(path.join(tmpdir(), "sarj-sonarjs-"));
  try {
    writeFileSync(
      path.join(root, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        plugins: [],
        jsPlugins: [{ name: "sarj-sonarjs", specifier: plugin }],
        overrides: controls.map((control) => ({
          files: [`${control.name}.ts`],
          rules: {
            [`sarj-sonarjs/${control.rule}`]:
              control.rule === "no-identical-functions"
                ? ["error", 3]
                : "error",
          },
        })),
      }),
    );
    for (const control of controls)
      writeFileSync(path.join(root, `${control.name}.ts`), control.source);
    const result = run(root);
    expect(result).toMatchObject({ status: 1, stderr: "" });
    const diagnostics = (
      JSON.parse(result.stdout) as {
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
            () => `${control.name}.ts:sarj-sonarjs(${control.rule})`,
          ),
        )
        .toSorted(),
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

it("retains native immediate-return fixes and redundant-jump suggestions without changing typed contracts", () => {
  const root = mkdtempSync(path.join(tmpdir(), "sarj-sonar-fix-"));
  try {
    writeFileSync(
      path.join(root, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        plugins: [],
        jsPlugins: [{ name: "sarj-sonarjs", specifier: plugin }],
        rules: {
          "sarj-sonarjs/prefer-immediate-return": "error",
          "sarj-sonarjs/no-redundant-jump": "error",
        },
      }),
    );
    writeFileSync(
      path.join(root, "return.ts"),
      "function run(){const value=load();return value;}",
    );
    writeFileSync(path.join(root, "jump.ts"), "function run(){work();return;}");
    const fixed = run(root, "--fix", "--fix-suggestions");
    expect(fixed).toMatchObject({ status: 0, stderr: "" });
    expect(readFileSync(path.join(root, "return.ts"), "utf8")).toBe(
      "function run(){return load();}",
    );
    expect(readFileSync(path.join(root, "jump.ts"), "utf8")).toBe(
      "function run(){work();}",
    );
    expect(run(root)).toMatchObject({ status: 0, stderr: "" });
    expect(run(root, "--fix", "--fix-suggestions")).toMatchObject({
      status: 0,
      stderr: "",
    });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

it("exposes the exact opt-in source profile without widening shared defaults", async () => {
  const options = { root: process.cwd(), typeAware: false };
  const baseline = await createStrictOxlintConfig(options);
  const enabled = await createStrictOxlintConfig({ ...options, sonarjs: true });
  const rules = Object.keys(SONARJS_ADDITIONAL_RULES);
  expect(rules).toHaveLength(8);
  expect(
    SONARJS_ADDITIONAL_RULES["sarj-sonarjs/no-identical-functions"],
  ).toEqual(["error", 3]);
  for (const rule of rules) {
    expect(
      baseline.overrides?.find((override) => rule in (override.rules ?? {}))
        ?.rules?.[rule],
    ).toBe("off");
    expect(
      enabled.overrides?.find((override) => rule in (override.rules ?? {}))
        ?.rules?.[rule],
    ).toEqual(
      SONARJS_ADDITIONAL_RULES[rule as keyof typeof SONARJS_ADDITIONAL_RULES],
    );
  }
});
