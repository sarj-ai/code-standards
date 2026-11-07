import { describe, expect, it } from "vitest";

import {
  ADDITIONS,
  CONTEXTS,
  MANAGED,
  RULE_MAP,
  effectiveRules,
  expectedOptions,
  oxlintIds,
  type Context,
} from "./managed-config.js";

const CONTEXT_IDS = Object.keys(CONTEXTS) as Context[];
const EFFECTIVE = new Map(CONTEXT_IDS.map((context) => [context, effectiveRules(MANAGED, CONTEXTS[context])]));
const rulesIn = (context: Context): ReadonlyMap<string, readonly unknown[]> => EFFECTIVE.get(context) ?? new Map();

describe("oxlint.rule-map.json", () => {
  it("gives every rule that does not run as itself a reason", () => {
    const unexplained = Object.entries(RULE_MAP)
      .filter(([, entry]) => (entry.kind === "replaced" || entry.kind === "dropped") && (entry.reason ?? "") === "")
      .map(([id]) => id);
    expect(unexplained).toEqual([]);
    const droppedWithTarget = Object.entries(RULE_MAP).filter(([, entry]) => entry.kind === "dropped" && entry.oxlintId !== null);
    expect(droppedWithTarget).toEqual([]);
  });

  it("runs each native and JS plugin rule in exactly the contexts ESLint enabled it, with the same options", () => {
    const mismatches: string[] = [];
    for (const [eslintId, entry] of Object.entries(RULE_MAP)) {
      if (entry.kind !== "native" && entry.kind !== "js-alias") continue;
      const [oxlintId = ""] = oxlintIds(entry);
      for (const context of CONTEXT_IDS) {
        const level = entry.contexts[context];
        const actual = rulesIn(context).get(oxlintId);
        if (level === undefined) {
          if (actual !== undefined) mismatches.push(`${eslintId}: ${oxlintId} is on in ${context}`);
          continue;
        }
        const expected = [oxlintId.startsWith("@sarj/") ? actual?.[0] : level, ...expectedOptions(entry, context)];
        if (JSON.stringify(actual) !== JSON.stringify(expected)) {
          mismatches.push(`${eslintId}: ${oxlintId} in ${context} is ${JSON.stringify(actual)}, expected ${JSON.stringify(expected)}`);
        }
      }
    }
    expect(mismatches).toEqual([]);
  });

  it("turns on every replacement wherever the replaced rule ran", () => {
    const missing = Object.entries(RULE_MAP).flatMap(([eslintId, entry]) =>
      entry.kind !== "replaced"
        ? []
        : oxlintIds(entry).flatMap((oxlintId) =>
            Object.keys(entry.contexts)
              .filter((context) => !rulesIn(context as Context).has(oxlintId))
              .map((context) => `${eslintId} -> ${oxlintId} in ${context}`)));
    expect(missing).toEqual([]);
  });

  it("accounts for every rule the config turns on", () => {
    const known = new Set([
      ...Object.values(RULE_MAP).flatMap(oxlintIds),
      ...Object.keys(ADDITIONS.rules),
    ]);
    const unknown = new Set(CONTEXT_IDS.flatMap((context) => [...rulesIn(context).keys()]).filter((id) => !known.has(id)));
    expect([...unknown]).toEqual([]);
  });
});
