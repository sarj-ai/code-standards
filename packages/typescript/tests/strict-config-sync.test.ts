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

  /**
   * The reverse direction, which is the one that actually failed. The check
   * above catches a config naming a rule that does not exist — loud at consumer
   * lint time. It cannot catch a rule that EXISTS but is never referenced, which
   * is silent: 2.8.0 and 2.9.0 shipped 12 rules that no consumer of
   * `sarj-lint-configs` ever ran. Same "written but inert" failure the rules
   * themselves were added to prevent, one layer up.
   */
  it("every plugin rule is either wired into the strict config or explicitly opted out", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = new Set(
      Array.from(
        text.matchAll(/"@sarj\/([a-z0-9-]+)"\s*:/gu),
        (match) => match[1] ?? "",
      ),
    );

    // Architectural rules whose options are inherently per-repo, so a SHARED
    // config cannot set them meaningfully. Each is documented as an opt-in in
    // eslint.strict.mjs. Adding a name here is a deliberate act — it must come
    // with that documentation, or the exemption is just a way to hide drift.
    const PER_REPO_OPT_IN = new Set([
      "no-storage-in-stateless-modules", // inert without `modules`
      "no-raw-fetch-outside-clients", // needs a repo-specific `allow` list
    ]);

    const unwired = Object.keys(rules)
      .filter((name) => !referenced.has(name) && !PER_REPO_OPT_IN.has(name))
      .sort();
    expect(unwired).toEqual([]);

    // And the opt-outs must actually be documented, not silently listed here.
    for (const name of PER_REPO_OPT_IN) {
      expect(text).toContain(name);
    }
  });

  it("plugin meta.version matches package.json version", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(HERE, "../package.json"), "utf8"),
    ) as { version: string };
    expect(plugin.meta.version).toBe(packageJson.version);
  });

});
