import { fileURLToPath } from "node:url";

import parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import strictConfig from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const RULE = "better-tailwindcss/enforce-consistent-variable-syntax";
const TAILWIND = (strictConfig as Linter.Config[]).find((entry) => entry.plugins?.["better-tailwindcss"]);

function configuration(): Linter.Config[] {
  const plugin = TAILWIND?.plugins?.["better-tailwindcss"];
  const rule = TAILWIND?.rules?.[RULE];
  if (plugin === undefined || rule === undefined) throw new Error("The shipped Tailwind policy is missing");
  return [{
    files: ["**/*.tsx"],
    languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "better-tailwindcss": plugin },
    rules: { [RULE]: rule },
  }];
}

describe("Tailwind variable shorthand", () => {
  it("ships only the scoped new warning", () => {
    expect(TAILWIND?.rules?.[RULE]).toEqual(["warn", { syntax: "shorthand" }]);
    expect(TAILWIND?.rules?.["better-tailwindcss/no-concatenated-classes"]).toBeUndefined();
    expect(TAILWIND?.rules?.["better-tailwindcss/enforce-consistent-important-position"]).toBeUndefined();
  });

  it.each([
    ['<div className="bg-[var(--brand)]" />', '<div className="bg-(--brand)" />'],
    ['<div className="bg-[var(--brand,red)]" />', '<div className="bg-(--brand,red)" />'],
    ['<div className="hover:bg-[var(--brand)]!" />', '<div className="hover:bg-(--brand)!" />'],
  ])("fixes and converges: %s", (source, expected) => {
    const engine = new Linter({ cwd: ROOT });
    const options = { filename: "src/probe.tsx" };
    expect(engine.verify(source, configuration(), options)).toEqual([
      expect.objectContaining({ ruleId: RULE, severity: 1 }),
    ]);
    const fixed = engine.verifyAndFix(source, configuration(), options);
    expect(fixed).toMatchObject({ fixed: true, output: expected, messages: [] });
    expect(engine.verifyAndFix(fixed.output, configuration(), options))
      .toMatchObject({ fixed: false, output: expected, messages: [] });
  });

  it.each([
    '<div className="bg-(--brand) hover:bg-(--brand)!" />',
    '<div style={{ background: "var(--brand)" }} />',
    '<div className="!flex" />',
  ])("leaves unrelated or already concise syntax alone: %s", (source) => {
    expect(new Linter({ cwd: ROOT }).verify(source, configuration(), { filename: "src/probe.tsx" })).toEqual([]);
  });
});
