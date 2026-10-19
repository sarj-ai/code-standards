import { resolve } from "node:path";

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import { createConfig as createApplicationConfig } from "../../standards/src/sarj_standards/configs/eslint.application.mjs";
import { createConfig as createStrictConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const FIXTURE_DIR = resolve(import.meta.dirname, "fixtures/runs");
const RULE_ID = "sonarjs/no-selector-parameter";
type ConfigFactory = (options?: { tsconfigRootDir?: string; projectService?: boolean }) => Linter.Config[];
const CONFIG_FACTORIES: ReadonlyArray<readonly [string, ConfigFactory]> = [
  ["strict", createStrictConfig],
  ["application", createApplicationConfig],
];

function focusedConfig(createConfig: ConfigFactory): Linter.Config[] {
  return createConfig({ tsconfigRootDir: FIXTURE_DIR }).map(entry => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => id === RULE_ID)),
  }));
}

describe.each(CONFIG_FACTORIES)("%s boolean selector policy", (_name, createConfig) => {
  const eslint = new ESLint({ cwd: FIXTURE_DIR, overrideConfigFile: true, overrideConfig: focusedConfig(createConfig) });
  it.each([
    "export function book(premium: boolean) { if (premium) { return premiumBook(); } else { return regularBook(); } }",
    "export function book(premium = false) { if (premium) { return premiumBook(); } else { return regularBook(); } }",
    "type BookingFlag = boolean; export function book(premium: BookingFlag) { if (premium) { return premiumBook(); } else { return regularBook(); } }",
    "export function book(premium: boolean) { return premium ? premiumBook() : regularBook(); }",
    "export const book = (premium: boolean) => { if (premium) { premiumBook(); } else { regularBook(); } };",
    "export class Booking { book(premium: boolean) { if (premium) { premiumBook(); } else { regularBook(); } } }",
    "export async function book(premium: boolean) { if (premium) { return await premiumBook(); } else { return await regularBook(); } }",
    "export function book(premium: boolean) { if (!premium) { regularBook(); } else { premiumBook(); } }",
    "export const book = function(premium: boolean) { if (premium) { premiumBook(); } else { regularBook(); } };",
    "export function book(premium: boolean) { return premium ? new PremiumBooking() : new RegularBooking(); }",
  ])("warns on a boolean choosing between operations: %s", async source => {
    const [result] = await eslint.lintText(source, { filePath: "example.ts" });
    expect(result?.messages.map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual([{ ruleId: RULE_ID, severity: 1 }]);
    expect(result?.messages[0]?.message).toContain("Provide multiple methods");
    expect(result?.messages[0]?.fix).toBeUndefined();
  });

  it.each([
    "export function regularBook() { return bookRegularSeat(); }",
    "export function book(mode: 'regular' | 'premium') { if (mode === 'premium') { premiumBook(); } else { regularBook(); } }",
    "export function setEnabled(enabled: boolean) { state.enabled = enabled; }",
    "export function enabled(value: boolean) { return value; }",
    "export function label(value: boolean) { return value ? 'Enabled' : 'Disabled'; }",
    "export function book({ premium }: { premium: boolean }) { if (premium) { premiumBook(); } else { regularBook(); } }",
    "source.subscribe((enabled: boolean) => { if (enabled) { start(); } else { stop(); } });",
    "source.subscribe(function(enabled: boolean) { if (enabled) { start(); } else { stop(); } });",
    "export function isEnabled() { return true; }",
    "export class Flags { set enabled(value: boolean) { this.current = value; } }",
    "export function book(flags: boolean[]) { if (flags.length > 0) { premiumBook(); } else { regularBook(); } }",
  ])("preserves data, explicit modes, options and callbacks: %s", async source => {
    const [result] = await eslint.lintText(source, { filePath: "example.ts" });
    expect(result?.messages).toEqual([]);
  });

  it("supports an exact local exception with its reason", async () => {
    const [result] = await eslint.lintText([
      "export function book(premium: boolean) {",
      "// eslint-disable-next-line sonarjs/no-selector-parameter -- Public compatibility contract retains this signature.",
      "if (premium) { premiumBook(); } else { regularBook(); }",
      "}",
    ].join("\n"), { filePath: "example.ts" });
    expect(result?.messages).toEqual([]);
  });

  it("preserves named component callback contracts in JSX files", async () => {
    const [result] = await eslint.lintText([
      "export function Editor() {",
      "const handleToggle = (checked: boolean) => { if (checked) { enable(); } else { disable(); } };",
      "return <Toggle onCheckedChange={handleToggle} />;",
      "}",
    ].join("\n"), { filePath: "widget.tsx" });
    expect(result?.messages).toEqual([]);
  });

  it("leaves syntax-only projects independent of type services", async () => {
    const config = createConfig({ tsconfigRootDir: FIXTURE_DIR, projectService: false }).map(entry => ({
      ...entry,
      rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => id === RULE_ID)),
    }));
    const eslint = new ESLint({ cwd: FIXTURE_DIR, overrideConfigFile: true, overrideConfig: config });
    const [result] = await eslint.lintText("export function book(premium: boolean) { if (premium) { premiumBook(); } else { regularBook(); } }", { filePath: "example.ts" });
    expect(result?.messages).toEqual([]);
  });
});
