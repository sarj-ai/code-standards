/**
 * The plugin's own presets have to work in the config format consumers write.
 *
 * Before 5.0.0 they did not. Both declared `plugins: ["@sarj"]` — eslintrc
 * syntax — and ESLint 9 rejects it on sight with "Key `plugins`: This appears to
 * be in eslintrc format (array of strings) rather than flat config format
 * (object)". So `sarj.configs.strict`, the documented way to get these rules
 * WITHOUT copying `eslint.strict.mjs`, threw for everyone who tried it, and the
 * only thing that worked was copying the shared config and editing the copy.
 * That is the vendoring these presets exist to prevent — one measured copy had
 * drifted 30 rules behind while carrying 5 that no longer exist upstream.
 *
 * `strict-config-loads.test.ts` covers the shared config; this covers the
 * lighter path a TypeScript repo can take with one npm package and no Python.
 */

import { ESLint, type Linter } from "eslint";
import { describe, expect, it } from "vitest";

import plugin, { recommendedRules, strictRules } from "../src/index.js";

const PRESETS = ["recommended", "strict"] as const;

describe("configs.recommended / configs.strict are flat config", () => {
  it.each(PRESETS)("%s loads through ESLint without throwing", async (name) => {
    const eslint = new ESLint({
      overrideConfigFile: true,
      overrideConfig: [
        { files: ["**/*.ts"] },
        plugin.configs[name],
      ] as Linter.Config[],
    });
    const resolved = await eslint.calculateConfigForFile("src/index.ts");
    const configured = Object.keys(resolved.rules ?? {});
    // A preset that resolved to nothing would pass "did not throw" while
    // enforcing nothing, which is the same silence the eslintrc shape produced.
    expect(configured.length).toBeGreaterThan(40);
    expect(configured.every((rule) => rule.startsWith("@sarj/"))).toBe(true);
  });

  it.each(PRESETS)("%s declares plugins as an object, not an array", (name) => {
    const preset = plugin.configs[name];
    expect(Array.isArray(preset.plugins)).toBe(false);
    expect(Object.keys(preset.plugins)).toEqual(["@sarj"]);
  });

  it.each(PRESETS)("%s carries rules and nothing that fights a host config", (name) => {
    // No `files`, no parser, no languageOptions: the presets compose with
    // whatever a repo already has. A `files` key here would silently narrow
    // every config spread after them.
    expect(Object.keys(plugin.configs[name]).sort()).toEqual([
      "name",
      "plugins",
      "rules",
    ]);
  });

  it("strict wires every rule the plugin ships", () => {
    // `recommended` deliberately omits some (strict-only architectural rules,
    // and ones that need per-repo options to mean anything), but `strict` is
    // the "every rule at error" preset -- a rule missing from it is a rule
    // that shipped and runs nowhere, which is the same written-but-inert
    // failure the rules themselves exist to catch, one layer up.
    //
    // Deprecated aliases are the one exception, and they are exempt because
    // wiring one would report the same defect twice under two names. That they
    // stay resolvable, deprecated and out of both presets is asserted in
    // `rule-docs.test.ts`.
    const known = Object.entries(plugin.rules)
      .filter(([, rule]) => rule.meta.deprecated === undefined)
      .map(([rule]) => `@sarj/${rule}`);
    const missing = known.filter((rule) => !(rule in strictRules));
    expect(missing).toEqual([]);

    const wiredAliases = Object.entries(plugin.rules)
      .filter(([, rule]) => rule.meta.deprecated !== undefined)
      .map(([rule]) => `@sarj/${rule}`)
      .filter((rule) => rule in strictRules);
    expect(wiredAliases).toEqual([]);
  });

  it("recommended is a subset of strict, never the other way round", () => {
    const extra = Object.keys(recommendedRules).filter(
      (rule) => !(rule in strictRules),
    );
    expect(extra).toEqual([]);
  });

  it("strict is at least as strict as recommended, rule for rule", () => {
    const weaker: string[] = [];
    for (const [rule, recommended] of Object.entries(recommendedRules)) {
      const strict = (strictRules as Record<string, unknown>)[rule];
      const severityOf = (value: unknown): unknown =>
        Array.isArray(value) ? value[0] : value;
      if (severityOf(recommended) === "error" && severityOf(strict) !== "error") {
        weaker.push(rule);
      }
    }
    expect(weaker).toEqual([]);
  });
});
