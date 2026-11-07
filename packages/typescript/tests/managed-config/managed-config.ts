
import { readFileSync } from "node:fs";
import { matchesGlob } from "node:path";

import type { OxlintConfig } from "oxlint";

import { createConfig, type TestFramework } from "../../../standards/src/sarj_standards/configs/oxlint.strict.mjs";

export { createConfig } from "../../../standards/src/sarj_standards/configs/oxlint.strict.mjs";

export const CONFIGS_DIR = new URL("../../../standards/src/sarj_standards/configs/", import.meta.url);

export const CONTEXTS = {
  "source-ts": "src/example.ts",
  "source-tsx": "src/example.tsx",
  "source-js": "src/example.js",
  "source-jsx": "src/example.jsx",
  "test-ts": "tests/example.test.ts",
  "test-bun-ts": "tests/example.bun.test.ts",
  "test-playwright-ts": "tests/example.playwright.ts",
  "config-ts": "vite.config.ts",
  "design-system-tsx": "src/components/ui/example.tsx",
} as const;
export type Context = keyof typeof CONTEXTS;

export const ALL_TEST_FRAMEWORKS: readonly TestFramework[] = ["vitest", "bun", "node", "testing-library", "playwright"];

export interface MapEntry {
  readonly kind: "native" | "js-alias" | "replaced" | "dropped";
  readonly oxlintId: string | readonly string[] | null;
  readonly contexts: Readonly<Partial<Record<Context, "error" | "warn">>>;
  readonly options?: readonly unknown[];
  readonly optionsByContext?: Readonly<Partial<Record<Context, readonly unknown[]>>>;
  readonly oxlintOptions?: readonly unknown[];
  readonly reason?: string;
}

export const RULE_MAP = JSON.parse(readFileSync(new URL("oxlint.rule-map.json", CONFIGS_DIR), "utf8")) as Readonly<Record<string, MapEntry>>;

export interface Additions {
  readonly jsPlugins: readonly { readonly name: string; readonly specifier: string }[];
  readonly rules: Readonly<Record<string, { readonly level: "error" | "warn"; readonly files?: string }>>;
}

export const ADDITIONS = JSON.parse(
  readFileSync(new URL("../../scripts/oxlint/stage2-rule-additions.json", import.meta.url), "utf8"),
) as Additions;

export type Setting = readonly unknown[];

export function effectiveRules(config: OxlintConfig, path: string): Map<string, Setting> {
  const rules = new Map<string, Setting>();
  const apply = (entries: Readonly<Record<string, unknown>> = {}): void => {
    for (const [id, raw] of Object.entries(entries)) {
      const setting: Setting = Array.isArray(raw) ? raw : [raw];
      if (setting[0] === "off") rules.delete(id);
      else rules.set(id, setting);
    }
  };
  apply(config.rules);
  for (const override of config.overrides ?? []) {
    const matches = (globs: readonly string[] | undefined): boolean => (globs ?? []).some((glob) => matchesGlob(path, glob));
    if (matches(override.files) && !matches(override.excludeFiles ?? undefined)) apply(override.rules);
  }
  return rules;
}

export function jsPlugins(config: OxlintConfig): { readonly name: string; readonly specifier: string }[] {
  return (config.jsPlugins ?? []).map((plugin) => {
    // eslint-disable-next-line @sarj/no-runtime-typeof -- Oxlint's ExternalPluginEntry is a bare specifier string or a named entry.
    if (typeof plugin === "string") throw new Error(`unnamed JS plugin ${plugin}`);
    return plugin;
  });
}

export function oxlintIds(entry: MapEntry): readonly string[] {
  if (entry.oxlintId === null) return [];
  // eslint-disable-next-line @sarj/no-runtime-typeof -- the rule map stores one Oxlint ID as a string and several as an array.
  return typeof entry.oxlintId === "string" ? [entry.oxlintId] : entry.oxlintId;
}

export function expectedOptions(entry: MapEntry, context: Context): readonly unknown[] {
  return entry.oxlintOptions ?? entry.optionsByContext?.[context] ?? entry.options ?? [];
}

export const MANAGED = createConfig({ testFrameworks: ALL_TEST_FRAMEWORKS });
