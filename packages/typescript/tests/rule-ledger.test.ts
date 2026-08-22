/**
 * Keeps the shipped rule ledger equal to this plugin's rule set.
 *
 * Deleting an ESLint rule is not a lint-level change for the repos using it.
 * A flat config that still names it makes ESLint exit 2 before it reads a single
 * file — `Could not find "@sarj/<rule>" in plugin "@sarj"` — and the strict
 * config sets `reportUnusedDisableDirectives: "error"`, so every orphaned
 * `eslint-disable` is an error of its own. The repo becomes unlintable on the
 * upgrade, with nothing in the failure saying the rule went deliberately.
 *
 * `rule-ledger.json` is what `sarj-standards doctor` reads to name those
 * references BEFORE the upgrade. It only helps if it is current, so removing a
 * rule fails here until `make sync-rule-ledger` has run — and that script
 * retires rather than deletes, which is how the removal ends up recorded.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { RENAMED_RULES, RETIRED_RULES, RULES } from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const LEDGER_PATH = resolve(
  HERE,
  "../../standards/src/sarj_standards/configs/rule-ledger.json",
);

interface RetiredEntry {
  readonly id: string;
  readonly kind: "code" | "eslint" | "python";
  readonly status: "removed" | "renamed";
  readonly replacement: string | null;
  readonly note: string;
}

interface Ledger {
  readonly rules: Readonly<Record<string, readonly string[]>>;
  readonly retired: readonly RetiredEntry[];
}

const LEDGER = JSON.parse(readFileSync(LEDGER_PATH, "utf8")) as Ledger;

describe("rule ledger", () => {
  it("lists exactly the rules this plugin exports", () => {
    expect([...LEDGER.rules.eslint].sort()).toEqual(Object.keys(RULES).sort());
  });

  it("does not claim a live rule was retired", () => {
    const live = new Set(Object.keys(RULES).map((name) => `@sarj/${name}`));
    const resurrected = LEDGER.retired
      .filter((entry) => entry.kind === "eslint" && live.has(entry.id))
      .map((entry) => entry.id);
    expect(resurrected).toEqual([]);
  });

  it("points every ESLint rename at a rule that exists", () => {
    const live = new Set(Object.keys(RULES).map((name) => `@sarj/${name}`));
    for (const entry of LEDGER.retired.filter(
      (candidate) => candidate.kind === "eslint" && candidate.status === "renamed",
    )) {
      expect(live.has(entry.replacement ?? "")).toBe(true);
    }
  });

  it("records a rename only for a name that stopped resolving", () => {
    // The ledger is what `doctor` reads to say "rewrite this reference". Saying
    // that about a name the plugin still registers would send a consumer to
    // change a line that works; saying nothing about one it no longer registers
    // leaves them with `ESLint: exit 2` and no replacement to reach for.
    const registered = Object.keys(plugin.rules);
    const stillLive = LEDGER.retired
      .filter((entry) => entry.kind === "eslint" && entry.status === "renamed")
      .map((entry) => entry.id)
      .filter((id) => registered.includes(id.replace("@sarj/", "")));
    expect(stillLive).toEqual([]);
  });

  it("records every rename the plugin itself declares", () => {
    const ledgerRenames = Object.fromEntries(
      LEDGER.retired
        .filter((entry) => entry.kind === "eslint" && entry.status === "renamed")
        .map((entry) => [entry.id, entry.replacement]),
    );
    const expected = Object.fromEntries(
      Object.entries(RENAMED_RULES).map(([from, to]) => [`@sarj/${from}`, `@sarj/${to}`]),
    );
    expect(ledgerRenames).toEqual(expected);
  });

  it("records every withdrawn plugin name as removed with no replacement", () => {
    const removed = Object.fromEntries(
      LEDGER.retired
        .filter((entry) => entry.kind === "eslint" && entry.status === "removed")
        .map((entry) => [entry.id.replace("@sarj/", ""), entry.replacement]),
    );
    const expected = Object.fromEntries(Object.keys(RETIRED_RULES).map((name) => [name, null]));
    expect(removed).toEqual(expected);
  });

  it("gives every withdrawn name a release and an actionable migration", () => {
    for (const entry of Object.values(RETIRED_RULES)) {
      expect(entry.removedIn).toMatch(/^\d+\.\d+\.\d+$/u);
      expect(entry.reason).toMatch(/^Delete\b/u);
      expect(entry.reason.match(/[.!?](?:\s|$)/gu)).toHaveLength(1);
    }
  });
});
