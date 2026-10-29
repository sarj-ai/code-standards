// vitest: shared-module-graph
















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
