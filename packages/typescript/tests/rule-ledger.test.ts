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
 * `rule-ledger.json` is what `sarj-lint-configs doctor` reads to name those
 * references BEFORE the upgrade. It only helps if it is current, so removing a
 * rule fails here until `make sync-rule-ledger` has run — and that script
 * retires rather than deletes, which is how the removal ends up recorded.
 */

import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import plugin, { renamedRules, rules } from "../src/index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const LEDGER_PATH = resolve(
  HERE,
  "../../lint-configs/src/sarj_lint_configs/configs/rule-ledger.json",
);

interface RetiredEntry {
  readonly id: string;
  readonly kind: string;
  readonly status: "removed" | "renamed";
  readonly replacement: string | null;
  readonly note: string;
}

interface Ledger {
  readonly rules: Readonly<Record<string, readonly string[]>>;
  readonly retired: readonly RetiredEntry[];
}

const ledger = JSON.parse(readFileSync(LEDGER_PATH, "utf8")) as Ledger;

describe("rule ledger", () => {
  it("lists exactly the rules this plugin exports", () => {
    expect([...ledger.rules.eslint].sort()).toEqual(Object.keys(rules).sort());
  });

  it("does not claim a live rule was retired", () => {
    const live = new Set(Object.keys(rules).map((name) => `@sarj/${name}`));
    const resurrected = ledger.retired
      .filter((entry) => entry.kind === "eslint" && live.has(entry.id))
      .map((entry) => entry.id);
    expect(resurrected).toEqual([]);
  });

  it("points every ESLint rename at a rule that exists", () => {
    const live = new Set(Object.keys(rules).map((name) => `@sarj/${name}`));
    for (const entry of ledger.retired) {
      if (entry.kind !== "eslint" || entry.status !== "renamed") continue;
      expect(live.has(entry.replacement ?? "")).toBe(true);
    }
  });

  it("records a rename only for a name that stopped resolving", () => {
    // The ledger is what `doctor` reads to say "rewrite this reference". Saying
    // that about a name the plugin still registers would send a consumer to
    // change a line that works; saying nothing about one it no longer registers
    // leaves them with `ESLint: exit 2` and no replacement to reach for.
    const registered = Object.keys(plugin.rules);
    const stillLive = ledger.retired
      .filter((entry) => entry.kind === "eslint" && entry.status === "renamed")
      .map((entry) => entry.id)
      .filter((id) => registered.includes(id.replace("@sarj/", "")));
    expect(stillLive).toEqual([]);
  });

  it("records every rename the plugin itself declares", () => {
    const ledgerRenames = Object.fromEntries(
      ledger.retired
        .filter((entry) => entry.kind === "eslint" && entry.status === "renamed")
        .map((entry) => [entry.id, entry.replacement]),
    );
    const expected = Object.fromEntries(
      Object.entries(renamedRules).map(([from, to]) => [`@sarj/${from}`, `@sarj/${to}`]),
    );
    expect(ledgerRenames).toEqual(expected);
  });

  it("records the rules deleted in 5.0.0, which consumers still name", () => {
    const removed = new Set(
      ledger.retired.filter((entry) => entry.kind === "eslint").map((entry) => entry.id),
    );
    expect(removed).toContain("@sarj/no-implicit-attribute-access");
    expect(removed).toContain("@sarj/prefer-setup-file-mocks");
    expect(removed).toContain("@sarj/ban-loose-type-guards-in-tests");
  });
});
