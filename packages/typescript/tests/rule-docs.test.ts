// vitest: shared-module-graph

















import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { RENAMED_RULES, RETIRED_RULES, RULES } from "../src/index.js";
import { examplesPath, examplesUrl, REPO_BLOB, TESTS_DIR } from "../src/rules/_docs.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "../../..");
const RULES_DIR = resolve(HERE, "../src/rules");







const MAX_FILEOVERVIEW_LINES = 6;





const EVIDENCE_IN_COMMENT =
  /((?<![-\w.#/])\d{3,}|\d+(?:\.\d+)?%|\.tsx?:\d+|\bcorpus\b|\bsweep\b|false[- ]positives?\b|true positives?\b|\bmeasured\b|\bfindings?\b|\bhits?\b|\baudit\b|PR #\d+)/iu;

const RULE_NAMES = Object.keys(RULES).sort();
const MODULE_NAMES = readdirSync(RULES_DIR)
  .filter((file) => file.endsWith(".ts"))
  .map((file) => file.replace(/\.ts$/u, ""))
  .sort();
const HELPER_NAMES = MODULE_NAMES.filter((name) => name.startsWith("_"));

function moduleSource(name: string): string {
  return readFileSync(resolve(RULES_DIR, `${name}.ts`), "utf8");
}


function configuredSarjRuleNames(source: string): Set<string> {
  return new Set(
    Array.from(source.matchAll(/"@sarj\/([a-z0-9-]+)"\s*:/gu), (match) => match[1] ?? ""),
  );
}


function fileoverviewLines(source: string): string[] {
  if (!source.startsWith("/*")) return [];
  const end = source.indexOf("*/");
  return source
    .slice(0, end)
    .split("\n")
    .map((line) => line.replace(/^\s*\/?\*+/u, "").trim())
    .filter((line) => line.length > 0);
}


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
    expect(REPO_BLOB).toBe("https://github.com/sarj-ai/code-standards/blob/main");
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

  it.each(RULE_NAMES)("%s points meta.docs.url at its executable examples", (name) => {
    const rule = RULES[name as keyof typeof RULES];
    expect(rule.meta.docs?.url).toBe(examplesUrl(name));
  });
});

describe("every rule module is a claim plus its derived links", () => {
  it.each(MODULE_NAMES)("%s opens with a capped @fileoverview", (name) => {
    const lines = fileoverviewLines(moduleSource(name));
    expect(lines.length).toBeGreaterThan(0);
    expect(
      lines.length,
      `${name}: @fileoverview is ${lines.length} content lines, cap is ${MAX_FILEOVERVIEW_LINES}. ` +
        "Behavior belongs in its paired test.",
    ).toBeLessThanOrEqual(MAX_FILEOVERVIEW_LINES);
  });

  it.each(MODULE_NAMES)("%s states its own name and a claim on line one", (name) => {
    const [first] = fileoverviewLines(moduleSource(name));
    expect(first).toMatch(new RegExp(`^@fileoverview ${name} — \\S`, "u"));
  });

  it.each(RULE_NAMES)("%s carries the derived examples link", (name) => {
    expect(fileoverviewLines(moduleSource(name))).toContain(
      `Examples: ${examplesUrl(name)}`,
    );
  });

  it.each(HELPER_NAMES)("%s carries no examples link, having no test module", (name) => {
    expect(fileoverviewLines(moduleSource(name)).join("\n")).not.toContain("Examples:");
  });

  it.each(MODULE_NAMES.filter((name) => name !== "_docs"))("%s hand-writes no repo link", (name) => {
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
  it.each(RULE_NAMES)("%s has a non-empty examples module", (name) => {
    const file = resolve(REPO_ROOT, examplesPath(name));
    expect(statSync(file).size, `${examplesPath(name)} is empty`).toBeGreaterThan(0);
  });

  it.each(MODULE_NAMES)("%s carries no measurement in a code comment", (name) => {
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



    expect(SHIPPED_IN_6_1_0).toHaveLength(50);
    expect(new Set(SHIPPED_IN_6_1_0).size).toBe(SHIPPED_IN_6_1_0.length);
  });

  it("accounts for every name the previous major shipped", () => {



    const unaccounted = SHIPPED_IN_6_1_0.filter(
      (name) =>
        !(name in plugin.rules) && !(name in RENAMED_RULES) && !(name in RETIRED_RULES),
    );
    expect(
      unaccounted,
      "a shipped rule name stopped resolving with no record of where it went. " +
        "Record it in `RENAMED_RULES` (which `make sync-rule-ledger` turns into the " +
        "ledger row `doctor` reads) — or retire it deliberately by deleting the " +
        "rule, which `src/rules/_retired-rules.ts` records.",
    ).toEqual([]);
  });

  it("never both renames and retires the same name", () => {


    const both = Object.keys(RENAMED_RULES).filter((name) => name in RETIRED_RULES);
    expect(both).toEqual([]);
  });

  it("renames exactly the shipped names it claims to", () => {


    for (const from of Object.keys(RENAMED_RULES)) {
      expect(SHIPPED_IN_6_1_0).toContain(from);
    }

    const live = new Set(RULE_NAMES);
    const orphaned = SHIPPED_IN_6_1_0.filter(
      (name) => !live.has(name) && !(name in RENAMED_RULES) && !(name in RETIRED_RULES),
    );
    expect(orphaned).toEqual([]);
  });

  it("registers no old name — 9.0.0 deleted the deprecated aliases", () => {




    for (const from of Object.keys(RENAMED_RULES)) {
      expect(Object.keys(plugin.rules)).not.toContain(from);
    }
  });

  it("points every old name at a rule that exists", () => {
    for (const to of Object.values(RENAMED_RULES)) {
      expect(RULE_NAMES).toContain(to);
    }
  });

  it("deprecates no live rule, so no name points at a dead end", () => {
    for (const to of Object.values(RENAMED_RULES)) {
      expect(RULES[to].meta.deprecated).toBeUndefined();
    }
  });

  it("keeps the old names out of both presets", () => {


    for (const from of Object.keys(RENAMED_RULES)) {
      expect(plugin.configs.strict.rules).not.toHaveProperty(`@sarj/${from}`);
      expect(plugin.configs.recommended.rules).not.toHaveProperty(`@sarj/${from}`);
    }
  });

  it("leaves no old name in the shipped strict config", () => {
    const configured = configuredSarjRuleNames(
      readFileSync(
        resolve(REPO_ROOT, "packages/standards/src/sarj_standards/configs/eslint.strict.ts"),
        "utf8",
      ),
    );
    for (const from of Object.keys(RENAMED_RULES)) {
      expect(configured).not.toContain(from);
    }
  });

  it("records each migration on the live rule that generates docs and redirects", () => {
    for (const [from, to] of Object.entries(RENAMED_RULES)) {
      expect(RULES[to as keyof typeof RULES]).toBeDefined();
      expect(RULES[to as keyof typeof RULES]?.documentation?.aliases).toContain(from);
    }
  });
});
