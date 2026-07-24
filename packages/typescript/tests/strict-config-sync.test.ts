/**
 * Guards the seam between this plugin and the published lint-configs strict
 * flat config. A rule name referenced in eslint.strict.mjs but missing from
 * the plugin only surfaces at consumer lint time as "Definition for rule
 * '@sarj/...' was not found" — exactly the no-unsafe-cast wiring bug this
 * branch fixed — so pin it here where the plugin's tests already run.
 * (Loading eslint.strict.mjs through ESLint would need every third-party
 * plugin it imports installed here; a static parse of the @sarj references
 * is robust and dependency-free.)
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { rules } from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const STRICT_CONFIG_PATH = resolve(
  HERE,
  "../../lint-configs/src/sarj_lint_configs/configs/eslint.strict.mjs",
);

describe("lint-configs eslint.strict.mjs stays wired to the plugin", () => {
  it("references only rule names that exist in the plugin's rules export", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    // Rule keys only ("@sarj/<rule>":) — not the "@sarj/eslint-plugin" import.
    const referenced = Array.from(
      text.matchAll(/"@sarj\/([a-z0-9-]+)"\s*:/gu),
      (match) => match[1] ?? "",
    );
    expect(referenced.length).toBeGreaterThan(0);

    const known = new Set(Object.keys(rules));
    const missing = referenced.filter((name) => !known.has(name));
    expect(missing).toEqual([]);
  });

  it("plugin meta.version matches package.json version", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(HERE, "../package.json"), "utf8"),
    ) as { version: string };
    expect(plugin.meta.version).toBe(packageJson.version);
  });

  it("keeps no-hardcoded-ui-text registered but out of every config tier (adoption parked on i18n framework decision)", () => {
    expect(Object.keys(rules)).toContain("no-hardcoded-ui-text");
    const recommended = plugin.configs.recommended.rules as Record<string, unknown>;
    expect(recommended["@sarj/no-hardcoded-ui-text"]).toBeUndefined();
    const strict = plugin.configs.strict.rules as Record<string, unknown>;
    expect(strict["@sarj/no-hardcoded-ui-text"]).toBeUndefined();
  });
});
