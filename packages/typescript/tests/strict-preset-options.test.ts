import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it } from "vitest";
import { createStrictOxlintConfig } from "../dist/config.js";

it("preserves the adopted strict TypeScript operand, template and async return policies", async () => {
  const config = await createStrictOxlintConfig({
    root: process.cwd(),
    typeAware: false,
  });
  expect(config.rules?.["typescript/restrict-plus-operands"]).toEqual([
    "error",
    {
      allowAny: false,
      allowBoolean: false,
      allowNullish: false,
      allowNumberAndString: false,
      allowRegExp: false,
    },
  ]);
  expect(config.rules?.["typescript/restrict-template-expressions"]).toEqual([
    "error",
    {
      allowAny: false,
      allowBoolean: false,
      allowNever: false,
      allowNullish: false,
      allowNumber: false,
      allowRegExp: false,
    },
  ]);
  expect(config.rules?.["typescript/return-await"]).toEqual([
    "error",
    "error-handling-correctness-only",
  ]);
});

it("discovers owned type projects without activating typed lint from vendor projects", async () => {
  const root = await mkdtemp(join(tmpdir(), "sarj-type-project-"));
  try {
    await mkdir(join(root, "vendor"));
    await writeFile(join(root, "vendor", "tsconfig.json"), "{}");
    expect((await createStrictOxlintConfig({ root })).options?.typeAware).toBe(
      false,
    );
    expect(
      (await createStrictOxlintConfig({ root, typeAware: true })).options
        ?.typeAware,
    ).toBe(true);
    await mkdir(join(root, "src"));
    await writeFile(join(root, "src", "tsconfig.json"), "{}");
    expect((await createStrictOxlintConfig({ root })).options?.typeAware).toBe(
      true,
    );
    expect(
      (await createStrictOxlintConfig({ root, typeAware: false })).options
        ?.typeAware,
    ).toBe(false);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
