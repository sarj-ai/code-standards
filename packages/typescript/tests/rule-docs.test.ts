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
 * The shape is now fixed: `<name> — <claim>` plus the two DERIVED links. The
 * measurements live in `docs/rules/<name>.md`, the examples live in
 * `tests/rules/<name>.test.ts`, and both URLs are computed from the rule name by
 * `src/rules/_docs.ts` — so a rename breaks a test here instead of leaving a
 * dead link in a comment.
 *
 * There is NO budget file and no exemption list. Every rule was converted in one
 * change; an escape hatch would only be a place for the next 171 lines to land.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { renamedRules, retiredRules, rules } from "../src/index.js";
import {
  EVIDENCE_DIR,
  evidencePath,
  evidenceUrl,
  examplesPath,
  examplesUrl,
  REPO_BLOB,
  TESTS_DIR,
} from "../src/rules/_docs.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../../..");
const RULES_DIR = resolve(HERE, "../src/rules");

/**
 * Content lines allowed in a module's `@fileoverview`: the `<name> — <claim>`
 * summary, an optional second claim line, and the two derived link lines. The
 * cap is what stops the 171-line block growing back one useful paragraph at a
 * time.
 */
const MAX_FILEOVERVIEW_LINES = 6;

/**
 * Signals that a comment is carrying evidence rather than explaining the code
 * beneath it: a count, a percentage, a `file.ts:12` citation, or the vocabulary
 * of a measurement. All of it belongs in `docs/rules/<name>.md`, which a reader
 * can choose to open and which the rule's own `meta.docs.url` points at.
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

describe("the links are derived, not typed", () => {
  it("derives the examples path from the rule name", () => {
    expect(examplesPath("no-enum")).toBe(`${TESTS_DIR}/no-enum.test.ts`);
  });

  it("derives the evidence path from the rule name", () => {
    expect(evidencePath("no-enum")).toBe(`${EVIDENCE_DIR}/no-enum.md`);
  });

  it("hangs both URLs off the same repo blob", () => {
    expect(examplesUrl("no-enum")).toBe(`${REPO_BLOB}/${examplesPath("no-enum")}`);
    expect(evidenceUrl("no-enum")).toBe(`${REPO_BLOB}/${evidencePath("no-enum")}`);
  });

  it("tracks the name it is given, which is the whole point", () => {
    // A rename must move the link with it. A hand-written string would not.
    expect(evidenceUrl("made-up-rule")).toBe(`${REPO_BLOB}/docs/rules/made-up-rule.md`);
  });

  it.each(ruleNames)("%s points meta.docs.url at its derived evidence doc", (name) => {
    // `createRule` is `RuleCreator(evidenceUrl)`, so this is the runtime proof
    // that the derivation is wired rather than merely exported.
    const rule = rules[name as keyof typeof rules];
    expect(rule.meta.docs?.url).toBe(evidenceUrl(name));
  });
});

describe("every rule module is a claim plus its derived links", () => {
  it.each(moduleNames)("%s opens with a capped @fileoverview", (name) => {
    const lines = fileoverviewLines(moduleSource(name));
    expect(lines.length).toBeGreaterThan(0);
    expect(
      lines.length,
      `${name}: @fileoverview is ${lines.length} content lines, cap is ${MAX_FILEOVERVIEW_LINES}. ` +
        `Measurements belong in ${evidencePath(name)}; examples belong in a test.`,
    ).toBeLessThanOrEqual(MAX_FILEOVERVIEW_LINES);
  });

  it.each(moduleNames)("%s states its own name and a claim on line one", (name) => {
    const [first] = fileoverviewLines(moduleSource(name));
    expect(first).toMatch(new RegExp(`^@fileoverview ${name} — \\S`, "u"));
  });

  it.each(moduleNames)("%s carries the derived evidence link", (name) => {
    expect(fileoverviewLines(moduleSource(name))).toContain(
      `Evidence: ${evidenceUrl(name)}`,
    );
  });

  it.each(ruleNames)("%s carries the derived examples link", (name) => {
    expect(fileoverviewLines(moduleSource(name))).toContain(
      `Examples: ${examplesUrl(name)}`,
    );
  });

  it.each(helperNames)("%s carries no examples link, having no test module", (name) => {
    expect(fileoverviewLines(moduleSource(name)).join("\n")).not.toContain("Examples:");
  });

  it.each(moduleNames)("%s hand-writes no repo link", (name) => {
    if (name === "_docs") return; // where the derivation itself is defined
    const stray = moduleSource(name)
      .split("\n")
      .filter(
        (line) =>
          line.includes(REPO_BLOB) &&
          !line.includes(examplesUrl(name)) &&
          !line.includes(evidenceUrl(name)),
      );
    expect(stray).toEqual([]);
  });
});

describe("the evidence lives where the links point", () => {
  it.each(moduleNames)("%s has a non-empty evidence document", (name) => {
    const file = resolve(REPO_ROOT, evidencePath(name));
    expect(statSync(file).size, `${evidencePath(name)} is empty`).toBeGreaterThan(0);
  });

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
      `a measurement belongs in ${evidencePath(name)}, not in a comment`,
    ).toEqual([]);
  });

  it("ships no exemption or budget file", () => {
    // #182 proved zero exemptions is reachable in one change. A budget file is
    // only ever a place for the next unbounded block to land.
    const strays = readdirSync(HERE).filter((file) => /budget|exempt|allowlist/iu.test(file));
    expect(strays).toEqual([]);
  });
});

describe("a rename ships a map, not a hole", () => {
  /**
   * Every rule name the last published major shipped. Frozen — a name is added
   * when a rule ships and never edited afterwards.
   *
   * This is the assertion the `renamedRules` map cannot make about itself:
   * deleting an entry from that map deletes the only thing that knew the old
   * name existed, so the test that walks it passes on an empty map. Consumers
   * hold these names in configs, disable comments and suppression baselines, and
   * a name that simply stops resolving is the failure the SARJ110 renumber
   * caused. A name may be RETIRED, which is a separate, deliberate act; it may
   * not quietly vanish.
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
    "no-conditional-in-test",
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

  it("still resolves every name the previous major shipped, unless retired", () => {
    const gone = SHIPPED_IN_6_1_0.filter(
      (name) => !(name in plugin.rules) && !(name in retiredRules),
    );
    expect(
      gone,
      "a shipped rule name stopped resolving. Rename it through `renamedRules`, " +
        "which keeps the old name registered as a deprecated alias — or retire it " +
        "deliberately by deleting the rule, which `src/rules/_retired.ts` records.",
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

  it("keeps every old name resolvable", () => {
    for (const from of Object.keys(renamedRules)) {
      expect(Object.keys(plugin.rules)).toContain(from);
    }
  });

  it("points every old name at a rule that exists", () => {
    for (const to of Object.values(renamedRules)) {
      expect(ruleNames).toContain(to);
    }
  });

  it("runs the same implementation under both names", () => {
    for (const [from, to] of Object.entries(renamedRules)) {
      const alias = plugin.rules[from as keyof typeof plugin.rules];
      const target = rules[to];
      expect(alias.create).toBe(target.create);
      expect(alias.meta.messages).toBe(target.meta.messages);
    }
  });

  it("marks every old name deprecated, naming its replacement", () => {
    for (const [from, to] of Object.entries(renamedRules)) {
      const alias = plugin.rules[from as keyof typeof plugin.rules];
      const deprecated = alias.meta.deprecated;
      expect(typeof deprecated).toBe("object");
      expect(deprecated).toMatchObject({
        replacedBy: [{ rule: { name: `@sarj/${to}` } }],
      });
      // The live rule must NOT be deprecated, or the map points at a dead end.
      expect(rules[to].meta.deprecated).toBeUndefined();
    }
  });

  it("keeps the old names out of both presets", () => {
    // Wiring an alias would double-report the same defect under two names, and
    // a consumer's shrink-only baseline would read the second as growth.
    for (const from of Object.keys(renamedRules)) {
      expect(plugin.configs.strict.rules).not.toHaveProperty(`@sarj/${from}`);
      expect(plugin.configs.recommended.rules).not.toHaveProperty(`@sarj/${from}`);
    }
  });

  it("leaves no old name in the shipped strict config or the README", () => {
    const config = readFileSync(
      resolve(REPO_ROOT, "packages/lint-configs/src/sarj_lint_configs/configs/eslint.strict.mjs"),
      "utf8",
    );
    const readme = readFileSync(resolve(HERE, "../README.md"), "utf8");
    for (const from of Object.keys(renamedRules)) {
      expect(config).not.toContain(`"@sarj/${from}"`);
      // The README documents the rename, so the old name may appear only in the
      // migration table — never as a live rule row.
      expect(readme).not.toContain(`| \`${from}\` |`);
    }
  });

  it("documents the migration where a consumer will look", () => {
    const readme = readFileSync(resolve(HERE, "../README.md"), "utf8");
    for (const [from, to] of Object.entries(renamedRules)) {
      expect(readme).toContain(from);
      expect(readme).toContain(to);
    }
  });
});
