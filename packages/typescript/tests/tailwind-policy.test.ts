import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import strictConfig from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const NO_TAILWIND_ROOT = mkdtempSync(join(tmpdir(), "sarj-no-tailwind-"));
const TAILWIND_CONFIG = (strictConfig as Linter.Config[]).find((entry) => entry.plugins?.["better-tailwindcss"]);
const CLASS_FRAGMENTS = "better-tailwindcss/no-concatenated-classes";
const VARIABLE_SYNTAX = "better-tailwindcss/enforce-consistent-variable-syntax";
const IMPORTANT_POSITION = "better-tailwindcss/enforce-consistent-important-position";
type PolicyRule = typeof CLASS_FRAGMENTS | typeof VARIABLE_SYNTAX | typeof IMPORTANT_POSITION;

afterAll(() => rmSync(NO_TAILWIND_ROOT, { recursive: true, force: true }));

function configuration(ruleName: PolicyRule): Linter.Config[] {
  const plugin = TAILWIND_CONFIG?.plugins?.["better-tailwindcss"];
  const configured = TAILWIND_CONFIG?.rules?.[ruleName];
  if (plugin === undefined || configured === undefined) throw new Error("The shipped Tailwind policy is missing");
  return [{
    files: ["**/*.tsx"],
    languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
    plugins: { "better-tailwindcss": plugin },
    rules: { [ruleName]: configured },
  }];
}

function lint(source: string, ruleName: PolicyRule = CLASS_FRAGMENTS, cwd = ROOT): Linter.LintMessage[] {
  return new Linter({ cwd }).verify(source, configuration(ruleName), { filename: "src/probe.tsx" });
}

describe("Tailwind class-fragment policy", () => {
  it.each([
    '<div className={styles[`size-${size}`]} />',
    'clsx(styles[`size-${size}`], "flex")',
    '<div className={styles.root + " " + styles[variant]} />',
    '<div className={`${base} ${active ? "bg-red-500" : "bg-blue-500"}`} />',
    '<div className={active ? "bg-red-500" : "bg-blue-500"} />',
    'const styles = `https://${host}`;',
    'const url = `https://${host}`;',
    'cn("flex", active && "bg-red-500")',
    '<div className={`widget-card${accent ? " widget-card--accent" : ""}`} />',
    '<div className={`${accent ? "widget-card--accent " : ""}widget-card`} />',
    '<div className={`widget-card${accent ? " widget-card--accent" : ""} text-sm`} />',
    '<div className={(`widget-card${accent ? " widget-card--accent" : ""}` as string)} />',
  ])("preserves complete values and non-class expressions: %s", (source) => {
    expect(lint(source)).toEqual([]);
  });

  it.each([
    '<div className={`bg-${color}-500`} />',
    '<div className={"bg-" + color} />',
    '<div className={"bg-" + "red-500"} />',
    '<div className={"bg-" + color + "-500"} />',
    'cn("flex", `bg-${color}`)',
    'clsx({[`bg-${color}`]: active})',
    'cva("flex", { variants: { tone: { loud: `bg-${color}` } } })',
    '<div className={`bg-${accent ? "red" : ""}-500`} />',
    '<div className={`widget${accent ? " card " : ""}accent`} />',
    '<div className={("bg-" + color as string) + "-500"} />',
    '<div className={("bg-" + color)! + "-500"} />',
    '<div className={`bg-${""}${color}`} />',
    '<div className={`widget-node--${variant}`} />',
  ])("reports one advisory finding per class expression: %s", (source) => {
    const messages = lint(source);
    expect(messages).toHaveLength(1);
    expect(messages[0]).toMatchObject({
      ruleId: "better-tailwindcss/no-concatenated-classes",
      severity: 1,
      message: "Select complete class names rather than assembling fragments; use literals or a lookup map.",
    });
    expect(messages[0]?.fix).toBeUndefined();
    expect(messages[0]?.suggestions).toBeUndefined();
  });

  it("keeps separate class expressions independently actionable", () => {
    expect(lint('clsx(`bg-${color}`, `text-${size}`)')).toHaveLength(2);
  });

  it("does not suppress a real class fragment next to a computed lookup", () => {
    expect(lint('clsx(styles[`size-${size}`], `bg-${color}`)')).toHaveLength(1);
  });

  it("does not enforce Tailwind fragments without a Tailwind installation", () => {
    expect(lint('<div className={`bg-${color}`} />', CLASS_FRAGMENTS, NO_TAILWIND_ROOT)).toEqual([]);
  });
});

describe("Tailwind syntax policy", () => {
  it("ships the calibrated warning options", () => {
    expect(TAILWIND_CONFIG?.plugins?.["better-tailwindcss"]?.rules?.["no-concatenated-classes"]?.meta?.type).toBe("suggestion");
    expect(TAILWIND_CONFIG?.rules?.[CLASS_FRAGMENTS]).toEqual(["warn", { variables: [] }]);
    expect(TAILWIND_CONFIG?.rules?.[VARIABLE_SYNTAX]).toEqual(["warn", { syntax: "shorthand" }]);
    expect(TAILWIND_CONFIG?.rules?.[IMPORTANT_POSITION]).toBe("warn");
  });

  it.each([
    [IMPORTANT_POSITION, '<div className="!flex" />', '<div className="flex!" />'],
    [IMPORTANT_POSITION, '<div className="hover:!flex md:!block" />', '<div className="hover:flex! md:block!" />'],
    [VARIABLE_SYNTAX, '<div className="bg-[var(--brand)]" />', '<div className="bg-(--brand)" />'],
    [VARIABLE_SYNTAX, '<div className="bg-[var(--brand,red)]" />', '<div className="bg-(--brand,red)" />'],
    [VARIABLE_SYNTAX, '<div className="hover:bg-[var(--brand)]!" />', '<div className="hover:bg-(--brand)!" />'],
  ] as const)("converges without changing modifiers: %s %s", (ruleName, source, expected) => {
    const findings = lint(source, ruleName);
    expect(findings.length).toBeGreaterThan(0);
    expect(findings.every((finding) => finding.severity === 1 && finding.ruleId === ruleName)).toBe(true);
    const engine = new Linter({ cwd: ROOT });
    const first = engine.verifyAndFix(source, configuration(ruleName), { filename: "src/probe.tsx" });
    expect(first.output).toBe(expected);
    expect(first.messages).toEqual([]);
    expect(first.fixed).toBe(true);
    const second = engine.verifyAndFix(first.output, configuration(ruleName), { filename: "src/probe.tsx" });
    expect(second).toMatchObject({ fixed: false, output: expected, messages: [] });
  });

  it.each([
    [IMPORTANT_POSITION, '<div className="flex! hover:block!" />'],
    [VARIABLE_SYNTAX, '<div className="bg-(--brand) hover:bg-(--brand)!" />'],
    [VARIABLE_SYNTAX, '<div style={{ background: "var(--brand)" }} />'],
    [IMPORTANT_POSITION, 'const css = "display: flex !important";'],
  ] as const)("retains concise syntax and unrelated CSS: %s %s", (ruleName, source) => {
    expect(lint(source, ruleName)).toEqual([]);
  });
});
