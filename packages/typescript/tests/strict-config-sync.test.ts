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

  it("plugin meta.version matches package.json version", () => {
    const packageJson = JSON.parse(
      readFileSync(resolve(HERE, "../package.json"), "utf8"),
    ) as { version: string };
    expect(plugin.meta.version).toBe(packageJson.version);
  });

});
