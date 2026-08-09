/**
 * The doc-diet ratchet, ported from `sarj-python-lint`'s `test_rule_meta.py` /
 * `test_rule_links.py`.
 *
 * A rule module used to open with up to 171 lines of `@fileoverview`. That is
 * not documentation a reader gets to choose: it is the first screen of every
 * file, it goes stale silently, and none of this plugin's own comment rules
 * could see it — `no-comment-cruft` and friends exempt JSDoc, so the one place
 * in the repo where prose grew without limit was the one place nothing measured.
 *
 * The shape is fixed: `<name> — <claim>` plus a derived link to the executable
 * examples in `tests/rules/<name>.test.ts`.
 *
 * There is NO budget file and no exemption list. Every rule was converted in one
 * change; an escape hatch would only be a place for the next 171 lines to land.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { renamedRules, retiredRules, rules } from "../src/index.js";
import { examplesPath, examplesUrl, REPO_BLOB, TESTS_DIR } from "../src/rules/_docs.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../../..");
const RULES_DIR = resolve(HERE, "../src/rules");

/**
 * Content lines allowed in a module's `@fileoverview`: the `<name> — <claim>`
 * summary, an optional second claim line, and the derived examples link. The
 * cap is what stops the 171-line block growing back one useful paragraph at a
 * time.
 */
const MAX_FILEOVERVIEW_LINES = 6;

/**
 * Signals that a source comment is carrying a corpus report rather than
 * explaining the implementation beneath it.
 */
const EVIDENCE_IN_COMMENT =
  /((?<![-\w.#/])\d{3,}|\d+(?:\.\d+)?%|\.tsx?:\d+|\bcorpus\b|\bsweep\b|false[- ]positives?\b|true positives?\b|\bmeasured\b|\bfindings?\b|\bhits?\b|\baudit\b|PR #\d+)/iu;

const ruleNames = Object.keys(rules).sort();
const moduleNames = readdirSync(RULES_DIR)
  .filter((file) => file.endsWith(".ts"))
  .map((file) => file.replace(/\.ts$/u, ""))
  .sort();
const helperNames = moduleNames.filter((name) => name.startsWith("_"));

function moduleSource(name: string): string {
  return readFileSync(resolve(RULES_DIR, `${name}.ts`), "utf8");
}

/** The leading block comment's content lines, `*` prefixes and blanks removed. */
function fileoverviewLines(source: string): string[] {
  if (!source.startsWith("/*")) return [];
  const end = source.indexOf("*/");
  return source
    .slice(0, end)
    .split("\n")
    .map((line) => line.replace(/^\s*\/?\*+/u, "").trim())
    .filter((line) => line.length > 0);
}

/** Every comment line in a module, block and line comments alike. */
function commentLines(source: string): { line: number; text: string }[] {
  const out: { line: number; text: string }[] = [];
  let inBlock = false;
  source.split("\n").forEach((raw, index) => {
    const text = raw.trim();
    if (inBlock) {
      out.push({ line: index + 1, text });
      if (text.includes("*/")) inBlock = false;
      return;
    }
    if (text.startsWith("/*")) {
      out.push({ line: index + 1, text });
      if (!text.includes("*/")) inBlock = true;
      return;
    }
    if (text.startsWith("//")) out.push({ line: index + 1, text });
  });
  return out;
}

describe("the executable-example links are derived, not typed", () => {
  it("links to this repository's main branch", () => {
    expect(REPO_BLOB).toBe("https://github.com/sarj-ai/standards/blob/main");
  });

  it("keeps executable examples in the rule test directory", () => {
    expect(TESTS_DIR).toBe("packages/typescript/tests/rules");
  });

  it("derives the examples path from the rule name", () => {
    expect(examplesPath("no-enum")).toBe(`${TESTS_DIR}/no-enum.test.ts`);
  });

  it("hangs the URL off the repo blob", () => {
    expect(examplesUrl("no-enum")).toBe(`${REPO_BLOB}/${examplesPath("no-enum")}`);
  });

  it("tracks the name it is given, which is the whole point", () => {
    expect(examplesUrl("made-up-rule")).toBe(
      `${REPO_BLOB}/${TESTS_DIR}/made-up-rule.test.ts`,
    );
  });

  it.each(ruleNames)("%s points meta.docs.url at its executable examples", (name) => {
    const rule = rules[name as keyof typeof rules];
    expect(rule.meta.docs?.url).toBe(examplesUrl(name));
  });
});

describe("every rule module is a claim plus its derived links", () => {
  it.each(moduleNames)("%s opens with a capped @fileoverview", (name) => {
    const lines = fileoverviewLines(moduleSource(name));
    expect(lines.length).toBeGreaterThan(0);
    expect(
      lines.length,
      `${name}: @fileoverview is ${lines.length} content lines, cap is ${MAX_FILEOVERVIEW_LINES}. ` +
        "Behavior belongs in its paired test.",
    ).toBeLessThanOrEqual(MAX_FILEOVERVIEW_LINES);
  });

  it.each(moduleNames)("%s states its own name and a claim on line one", (name) => {
    const [first] = fileoverviewLines(moduleSource(name));
    expect(first).toMatch(new RegExp(`^@fileoverview ${name} — \\S`, "u"));
  });

  it.each(ruleNames)("%s carries the derived examples link", (name) => {
    expect(fileoverviewLines(moduleSource(name))).toContain(
      `Examples: ${examplesUrl(name)}`,
    );
  });

  it.each(helperNames)("%s carries no examples link, having no test module", (name) => {
    expect(fileoverviewLines(moduleSource(name)).join("\n")).not.toContain("Examples:");
  });

  it.each(moduleNames.filter((name) => name !== "_docs"))("%s hand-writes no repo link", (name) => {
    const stray = moduleSource(name)
      .split("\n")
      .filter(
        (line) =>
          line.includes(REPO_BLOB) &&
          !line.includes(examplesUrl(name)),
      );
    expect(stray).toEqual([]);
  });
});

describe("the behavior lives in executable tests", () => {
  it.each(ruleNames)("%s has a non-empty examples module", (name) => {
    const file = resolve(REPO_ROOT, examplesPath(name));
    expect(statSync(file).size, `${examplesPath(name)} is empty`).toBeGreaterThan(0);
  });

  it.each(moduleNames)("%s carries no measurement in a code comment", (name) => {
    const offenders = commentLines(moduleSource(name))
      .filter(({ text }) => EVIDENCE_IN_COMMENT.test(text))
      .map(({ line, text }) => `${name}.ts:${line}: ${text}`);
    expect(
      offenders,
      "Corpus reports do not belong in implementation comments; encode behavior in tests.",
    ).toEqual([]);
  });

  it("ships no exemption or budget file", () => {
    const strays = readdirSync(HERE).filter((file) => /budget|exempt|allowlist/iu.test(file));
    expect(strays).toEqual([]);
  });
});

describe("a rename ships a map, not a hole", () => {
  /**
   * Every rule name the 6.1.0 major shipped. Frozen — a name is added when a
   * rule ships and never edited afterwards.
   *
   * This is the assertion the `renamedRules` map cannot make about itself:
   * deleting an entry from that map deletes the only thing that knew the old
   * name existed, so the test that walks it passes on an empty map. Consumers
   * hold these names in configs, disable comments and suppression baselines, and
   * a name that simply stops resolving is the failure the SARJ110 renumber
   * caused. A name may be RETIRED or RENAMED, which are separate, deliberate
   * acts; it may not quietly vanish.
   *
   * "Retired" is not restated here. It is read from `retiredRules`, the same map
   * `strict-config-sync.test.ts` derives from git history — so a withdrawal is
   * recorded in exactly one place and this list never has to be edited for one.
   */
  const SHIPPED_IN_6_1_0: readonly string[] = [
    "enforce-file-structure",
    "jsdoc-restates-signature",
    "no-async-callback-in-waitfor",
    "no-client-side-data-fetching",
    "no-comment-cruft",
    "no-cors-wildcard-with-credentials",
    "no-dynamic-sql",
    "no-enum",
    "no-fat-try-blocks",
    "no-hand-rolled-sleep",
    "no-insecure-random-id",
    "no-json-stringify-error",
    "no-log-only-catch",
    "no-offset-pagination",
    "no-positional-tuple-return",
    "no-raw-env",
    "no-raw-fetch-outside-clients",
    "no-repeated-string-literal",
    "no-restated-comment",
    "no-secret-in-log",
    "no-select-star",
    "no-sentinel-return-on-catch",
    "no-silent-promise-catch",
    "no-sleep-in-test-body",
    "no-storage-in-stateless-modules",
    "no-string-concat-in-loop",
    "no-tautological-expect",
    "no-type-member-comment-wall",
    "no-unnecessary-use-client",
    "no-unsafe-mock-casting",
    "no-zod-native-enum",
    "prefer-constant-time-secret-compare",
    "prefer-discriminated-union",
    "prefer-module-level-constant",
    "prefer-module-level-schema",
    "prefer-non-nullable-collection",
    "prefer-schema-for-api-payload",
    "prefer-semantic-colors",
    "prefer-server-actions",
    "prefer-string-literal-union",
    "prefer-zod-enum",
    "prefer-zod-infer",
    "require-assert-never",
    "require-fetch-timeout",
    "require-interface-for-injected-service",
    "require-zod-form-validation",
    "store-insert-requires-on-conflict",
    "strict-test-assertions",
    "trailing-value-narration",
    "zod-naming-convention",
  ];

  it("froze the whole list, so a name cannot be dropped from the guard itself", () => {
    // Editing an entry OUT of this list would let the rule it names vanish with
    // nothing failing — the guard would delete its own evidence. The length is
    // the cheapest thing that notices.
    expect(SHIPPED_IN_6_1_0).toHaveLength(50);
    expect(new Set(SHIPPED_IN_6_1_0).size).toBe(SHIPPED_IN_6_1_0.length);
  });

  it("accounts for every name the previous major shipped", () => {
    // A shipped name is either still a rule, or recorded as renamed, or recorded
    // as retired. What it may never be is absent from all three, which is a name
    // that stopped resolving with nothing anywhere saying what to do instead.
    const unaccounted = SHIPPED_IN_6_1_0.filter(
      (name) =>
        !(name in plugin.rules) && !(name in renamedRules) && !(name in retiredRules),
    );
    expect(
      unaccounted,
      "a shipped rule name stopped resolving with no record of where it went. " +
        "Record it in `renamedRules` (which `make sync-rule-ledger` turns into the " +
        "ledger row `doctor` reads) — or retire it deliberately by deleting the " +
        "rule, which `src/rules/_retired.ts` records.",
    ).toEqual([]);
  });

  it("never both renames and retires the same name", () => {
    // The two maps answer opposite questions about one name; an entry in both is
    // a contradiction a consumer's migration script cannot resolve.
    const both = Object.keys(renamedRules).filter((name) => name in retiredRules);
    expect(both).toEqual([]);
  });

  it("renames exactly the shipped names it claims to", () => {
    // The map may only rename FROM a name that shipped: renaming from a name
    // nobody ever had is a typo that silently protects nothing.
    for (const from of Object.keys(renamedRules)) {
      expect(SHIPPED_IN_6_1_0).toContain(from);
    }
    // ...and every shipped name that is no longer a live rule must be in it.
    const live = new Set(ruleNames);
    const orphaned = SHIPPED_IN_6_1_0.filter(
      (name) => !live.has(name) && !(name in renamedRules) && !(name in retiredRules),
    );
    expect(orphaned).toEqual([]);
  });

  it("registers no old name — 9.0.0 deleted the deprecated aliases", () => {
    // 7.0.0 kept each old name registered as a deprecated alias. 9.0.0 deletes
    // them: the new names are the only names, and a config still naming an old
    // one gets `Could not find "@sarj/<rule>" in plugin "@sarj"` — which is why
    // the ledger has to carry the replacement (`rule-ledger.test.ts`).
    for (const from of Object.keys(renamedRules)) {
      expect(Object.keys(plugin.rules)).not.toContain(from);
    }
  });

  it("points every old name at a rule that exists", () => {
    for (const to of Object.values(renamedRules)) {
      expect(ruleNames).toContain(to);
    }
  });

  it("deprecates no live rule, so no name points at a dead end", () => {
    for (const to of Object.values(renamedRules)) {
      expect(rules[to].meta.deprecated).toBeUndefined();
    }
  });

  it("keeps the old names out of both presets", () => {
    // A preset naming a rule the plugin does not define is `Could not find
    // "@sarj/<rule>" in plugin "@sarj"` for every consumer of that preset.
    for (const from of Object.keys(renamedRules)) {
      expect(plugin.configs.strict.rules).not.toHaveProperty(`@sarj/${from}`);
      expect(plugin.configs.recommended.rules).not.toHaveProperty(`@sarj/${from}`);
    }
  });

  it("leaves no old name in the shipped strict config", () => {
    const config = readFileSync(
      resolve(REPO_ROOT, "packages/standards/src/sarj_standards/configs/eslint.strict.mjs"),
      "utf8",
    );
    for (const from of Object.keys(renamedRules)) {
      expect(config).not.toContain(`"@sarj/${from}"`);
    }
  });

  it("records each migration on the live rule that generates docs and redirects", () => {
    for (const [from, to] of Object.entries(renamedRules)) {
      expect(rules[to as keyof typeof rules]).toBeDefined();
      expect(rules[to as keyof typeof rules]?.documentation?.aliases).toContain(from);
    }
  });
});
