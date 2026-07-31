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

import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { renamedRules, retiredRules, rules } from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const STRICT_CONFIG_PATH = resolve(
  HERE,
  "../../lint-configs/src/sarj_lint_configs/configs/eslint.strict.mjs",
);
const REPO_ROOT = resolve(HERE, "../../..");

/** Run git at the repo root. Throws — a gate that reads history must not go quiet. */
function gitOutput(...args: readonly string[]): string {
  return execFileSync("git", ["-C", REPO_ROOT, ...args], {
    encoding: "utf8",
    maxBuffer: 32 * 1024 * 1024,
  });
}

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
  it("wires every plugin rule into the strict config", () => {
    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = new Set(referencedRuleNames(text));
    const unwired = Object.keys(rules)
      .filter((name) => !referenced.has(name))
      .sort();
    expect(unwired).toEqual([]);
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

  /**
   * A withdrawn name is burned, not recycled: consumers still carry
   * `eslint-disable` comments and `eslint-suppressions.json` entries naming it,
   * and reusing the name would silently re-point those suppressions at a rule
   * that means something else.
   */
  it("withdrawn rule names are never reused or left configured", () => {
    // `plugin.rules`, not `rules`: a retired name must not come back under any
    // registration the plugin publishes.
    const live = Object.keys(retiredRules).filter(
      (name) => name in plugin.rules,
    );
    expect(live).toEqual([]);

    const text = readFileSync(STRICT_CONFIG_PATH, "utf8");
    const referenced = new Set(referencedRuleNames(text));
    const stillConfigured = Object.keys(retiredRules).filter((name) =>
      referenced.has(name),
    );
    expect(stillConfigured).toEqual([]);
  });

  /**
   * The gate that keeps `src/rules/_retired.ts` honest, because a hand-kept list
   * is exactly what failed here before.
   *
   * The previous version of this test declared ONE name under a doc comment
   * claiming it mirrored the Python retired-code set — while the plugin had in
   * fact deleted eleven rules across five releases, including all three removed
   * in #183 and all five removed in 3.0.0. Nothing noticed, because nothing
   * derived anything: the list only failed when a human had remembered to edit
   * it.
   *
   * Git history is the derivation. A TypeScript rule's NAME is its filename, so
   * `--diff-filter=D` over `src/rules/` recovers every name ever withdrawn
   * without anyone writing it down. The comparison is an exact set equality in
   * both directions, so a deletion that forgets to add an entry fails, and so
   * does an entry invented for a rule that was never deleted.
   *
   * `--no-renames` is deliberate: a rule file that MOVED still has to be
   * accounted for, and `_renames.ts` is what distinguishes the two cases. It has
   * to be read directly rather than inferred from `plugin.rules`, because 9.0.0
   * deleted the deprecated aliases 7.0.0 registered — the four renamed-away
   * filenames are gone from the registry too, and a rename is still not a
   * withdrawal. `rule-docs.test.ts` keeps the two maps disjoint, so a name can
   * be excused by exactly one of them.
   */
  it("_retired.ts lists exactly the rule files git has seen deleted", () => {
    expect(gitOutput("rev-parse", "--is-shallow-repository").trim()).toBe(
      "false",
    );

    const log = gitOutput(
      "log",
      "--no-renames",
      "--diff-filter=D",
      "--name-only",
      "--format=",
      "HEAD",
      "--",
      "packages/typescript/src/rules",
    );

    const deleted = new Set<string>();
    for (const line of log.split("\n")) {
      const path = line.trim();
      if (!path.endsWith(".ts") || path.endsWith(".test.ts")) continue;
      const name = path.slice(path.lastIndexOf("/") + 1, -".ts".length);
      // `_tailwind.ts` and friends are shared helpers, never rule names.
      if (name.startsWith("_")) continue;
      // Still accounted for — re-added under the same name, or renamed, with
      // `_renames.ts` saying where it went. Neither is a withdrawal.
      if (name in plugin.rules || name in renamedRules) continue;
      deleted.add(name);
    }

    expect([...deleted].sort()).toEqual(Object.keys(retiredRules).sort());
  });
});
