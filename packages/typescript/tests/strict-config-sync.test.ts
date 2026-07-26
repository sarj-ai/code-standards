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

/**
 * Blank out line and block comments while leaving string and template contents
 * intact, so a `//` inside a URL literal is never mistaken for a comment.
 *
 * Matching over the raw file text does not work here, and the reason is exactly
 * the drift these tests exist to catch: the per-repo opt-ins are documented in
 * eslint.strict.mjs as commented-out example blocks containing the literal text
 * `"@sarj/no-raw-fetch-outside-clients": [...]`. A raw-text regex counts those
 * as live references, which (a) makes PER_REPO_OPT_IN dead code and (b) lets any
 * future rule pass BOTH assertions while only ever appearing in a comment.
 *
 * Newlines are preserved so the stripped text still lines up with the original.
 * Regex literals are not tracked — the config contains none, and a rule key
 * never sits inside one; string/template state is what the URL case needs.
 */
function stripComments(source: string): string {
  const QUOTES = new Set(["'", '"', "`"]);
  let out = "";
  let index = 0;

  while (index < source.length) {
    const char = source[index] ?? "";
    const next = source[index + 1] ?? "";

    if (char === "/" && next === "/") {
      while (index < source.length && source[index] !== "\n") index += 1;
      continue;
    }

    if (char === "/" && next === "*") {
      index += 2;
      while (
        index < source.length &&
        !(source[index] === "*" && source[index + 1] === "/")
      ) {
        if (source[index] === "\n") out += "\n";
        index += 1;
      }
      index += 2;
      continue;
    }

    if (QUOTES.has(char)) {
      const quote = char;
      out += char;
      index += 1;
      while (index < source.length && source[index] !== quote) {
        // A backslash escapes the next character, including the closing quote.
        if (source[index] === "\\") {
          out += source.slice(index, index + 2);
          index += 2;
          continue;
        }
        out += source[index];
        index += 1;
      }
      out += quote;
      index += 1;
      continue;
    }

    out += char;
    index += 1;
  }

  return out;
}

/** Rule names the strict config configures as LIVE rule keys, comments excluded. */
function referencedRuleNames(configText: string): string[] {
  // Rule keys only ("@sarj/<rule>":) — not the "@sarj/eslint-plugin" import.
  return Array.from(
    stripComments(configText).matchAll(/"@sarj\/([a-z0-9-]+)"\s*:/gu),
    (match) => match[1] ?? "",
  );
}

/**
 * Each rule's severity in the config's MAIN block, keyed by rule name.
 *
 * Deliberately takes the FIRST occurrence of a name. The main block comes first
 * in the file; the later `files:`-scoped blocks re-set some rules on purpose
 * (`"@sarj/no-raw-env": "off"` for env source-of-truth files). Those overrides
 * are the config doing its job, not tier drift, so only the base severity is
 * compared. Entries configured as `[severity, options]` arrays are skipped —
 * this config expresses every @sarj tier as a bare string today, and a static
 * parse should not pretend to read option tuples.
 */
function baseSeverities(configText: string): Map<string, string> {
  const found = new Map<string, string>();
  for (const match of stripComments(configText).matchAll(
    /"@sarj\/([a-z0-9-]+)"\s*:\s*"(\w+)"/gu,
  )) {
    const [, name, severity] = match;
    if (name !== undefined && severity !== undefined && !found.has(name)) {
      found.set(name, severity);
    }
  }
  return found;
}

describe("lint-configs eslint.strict.mjs stays wired to the plugin", () => {
  it("references only rule names that exist in the plugin's rules export", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = referencedRuleNames(text);
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
    const referenced = new Set(referencedRuleNames(text));

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

    // The opt-outs must actually be documented, not silently listed here. Now
    // that referencedRuleNames() ignores comments this is a genuinely separate
    // claim from being wired: "mentioned in the file" vs "configured".
    for (const name of PER_REPO_OPT_IN) {
      expect(text).toContain(name);
    }

    // ...and the exemption must still be needed. If someone wires an opt-in for
    // real, the stale entry has to go, or it silently re-opens the same hole for
    // whatever rule is added next.
    const redundant = [...PER_REPO_OPT_IN].filter((name) =>
      referenced.has(name),
    );
    expect(redundant).toEqual([]);
  });

  /**
   * The third drift axis. A rule can be present in both places and still not
   * mean the same thing: `no-repeated-string-literal` was wired at `warn` while
   * the plugin's own `configs.strict` has it at `error`, and the config's header
   * went on claiming its tiers "mirror the plugin's own configs.strict" with
   * `enforce-file-structure` as the single deviation. Silently shipping a
   * weaker tier than the plugin declares is the same class of lie as the stale
   * "@2.7.0" version line — true once, then quietly not.
   *
   * Deviations are allowed, but they have to be declared HERE with a reason,
   * which makes lowering a tier a reviewed edit instead of a diff nobody reads.
   */
  it("severities match the plugin's own strict preset, except where declared", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const configured = baseSeverities(text);
    const pluginStrict = plugin.configs.strict.rules as Record<string, string>;

    // rule -> [plugin tier, config tier, why the config deviates]
    // Empty by design as of this change: "strict" now means every rule at
    // `error` in BOTH the plugin's own configs.strict and the shared config, so
    // there is nothing left to declare. The two former entries
    // (enforce-file-structure, no-repeated-string-literal) were promoted rather
    // than kept as exceptions.
    //
    // Keep the mechanism. It is what makes lowering a tier a reviewed edit with
    // a written reason instead of a one-word diff nobody reads — and the drift
    // it catches is exactly how no-repeated-string-literal ended up at `warn`
    // under a header claiming the tiers already mirrored the plugin.
    const DECLARED_DEVIATIONS = new Map<string, readonly [string, string]>([]);

    const drift: string[] = [];
    for (const [name, pluginSeverity] of Object.entries(pluginStrict)) {
      const rule = name.replace("@sarj/", "");
      const configSeverity = configured.get(rule);
      if (configSeverity === undefined) {
        continue; // not wired — the opt-in assertion above owns that case
      }
      const declared = DECLARED_DEVIATIONS.get(rule);
      if (declared !== undefined) {
        // The declaration itself must stay true, or it is just a mute button.
        expect([rule, pluginSeverity, configSeverity]).toEqual([
          rule,
          declared[0],
          declared[1],
        ]);
        continue;
      }
      if (configSeverity !== pluginSeverity) {
        drift.push(`${rule}: plugin=${pluginSeverity} config=${configSeverity}`);
      }
    }
    expect(drift).toEqual([]);
  });

  it("plugin meta.version matches package.json version", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(HERE, "../package.json"), "utf8"),
    ) as { version: string };
    expect(plugin.meta.version).toBe(packageJson.version);
  });

});
