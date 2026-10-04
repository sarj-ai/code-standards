import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";
import { NEXTJS_ADDITIONAL_RECOMMENDED_RULES } from "../dist/presets.js";

interface Control {
  name: string;
  source: string;
  expected: number;
}
const controls = JSON.parse(
  readFileSync(
    new URL("./upstream-nextjs-controls.json", import.meta.url),
    "utf8",
  ),
) as Control[];
const engine = path.join(
  path.dirname(fileURLToPath(import.meta.resolve("oxlint/package.json"))),
  "bin/oxlint",
);

it("preserves Next relative navigation, static URL evidence and native global binding identity", () => {
  const directory = mkdtempSync(path.join(tmpdir(), "sarj-next-navigation-"));
  try {
    writeFileSync(
      path.join(directory, "oxlint.json"),
      JSON.stringify({
        categories: { correctness: "off" },
        env: { browser: true, es2024: true },
        jsPlugins: [
          {
            name: "sarj-nextjs",
            specifier: fileURLToPath(
              import.meta.resolve("@sarj/oxlint-plugin/upstream/nextjs"),
            ),
          },
        ],
        rules: NEXTJS_ADDITIONAL_RECOMMENDED_RULES,
      }),
    );
    for (const control of controls)
      writeFileSync(path.join(directory, `${control.name}.ts`), control.source);
    const run = spawnSync(
      process.execPath,
      [engine, "--config", "oxlint.json", "--format=json", "."],
      { cwd: directory, encoding: "utf8", timeout: 30_000 },
    );
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
            () =>
              `${control.name}.ts:sarj-nextjs(no-location-assign-relative-destination)`,
          ),
        )
        .toSorted(),
    );
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

it("leaves the Next addition disabled in shared defaults and exposes the explicit project profile", async () => {
  const options = { root: process.cwd(), typeAware: false };
  const baseline = await createStrictOxlintConfig(options);
  const enabled = await createStrictOxlintConfig({ ...options, nextjs: true });
  const rule = "sarj-nextjs/no-location-assign-relative-destination";
  expect(
    baseline.overrides?.find((override) => rule in (override.rules ?? {}))
      ?.rules?.[rule],
  ).toBe("off");
  expect(
    enabled.overrides?.find((override) => rule in (override.rules ?? {}))
      ?.rules?.[rule],
  ).toBe("error");
  expect(NEXTJS_ADDITIONAL_RECOMMENDED_RULES).toEqual({ [rule]: "error" });
});
