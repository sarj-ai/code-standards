import { Linter } from "eslint";
import * as tsParser from "@typescript-eslint/parser";
import { describe, expect, it } from "vitest";

import plugin from "../src/index.js";

// A large synthetic source that exercises the patterns the rules look for: loops with
// awaits and string concat, try/catch, fetch in effects, JSX, enums, zod, process.env.
const BLOCK = (i: number): string => `
async function handler_${i}(items: number[]): Promise<string> {
  let acc_${i} = "";
  for (const item of items) {
    acc_${i} = acc_${i} + String(item);
    const row_${i} = await fetch("/api/items/" + String(item));
    try {
      const data_${i} = await row_${i}.json();
      acc_${i} += String(data_${i});
    } catch (e_${i}) {
      console.error(e_${i});
      return null as unknown as string;
    }
  }
  const key_${i} = Math.random().toString(36);
  const mode_${i} = process.env.MODE_${i};
  return acc_${i} + key_${i} + String(mode_${i});
}

function View_${i}(): unknown {
  return null;
}
`;

const SOURCE = Array.from({ length: 90 }, (_, i) => BLOCK(i)).join("\n");
const LOC = SOURCE.split("\n").length;

const ABSOLUTE_MS_PER_KLOC = 200;
const RELATIVE_OUTLIER_FACTOR = 10;
const RELATIVE_SLACK_MS = 3;

const ruleNames = Object.keys(plugin.rules);

// Both tests need every rule's timing; measuring 57 rules x 6 verifies twice
// doubles a ~60s workload, so timings are shared across tests.
const timingCache = new Map<string, number>();

function bestMs(ruleName: string, repeats = 5): number {
  const cached = timingCache.get(ruleName);
  if (cached !== undefined) {
    return cached;
  }
  const linter = new Linter();
  const config: Linter.Config[] = [
    {
      files: ["**/*.tsx"],
      languageOptions: {
        parser: tsParser as Linter.Parser,
        parserOptions: { ecmaFeatures: { jsx: true }, sourceType: "module" },
      },
      plugins: { "@sarj": plugin as unknown as Record<string, unknown> },
      rules: { [`@sarj/${ruleName}`]: "error" },
    },
  ];
  // Warm up the parser + rule JIT first so the absolute gate isn't flaky on a
  // cold process (the first parse of a fresh run is several times slower).
  linter.verify(SOURCE, config, "synthetic.tsx");
  let best = Number.POSITIVE_INFINITY;
  for (let r = 0; r < repeats; r++) {
    const start = performance.now();
    linter.verify(SOURCE, config, "synthetic.tsx");
    best = Math.min(best, performance.now() - start);
  }
  timingCache.set(ruleName, best);
  return best;
}

// These re-parse a ~2k-line source many times; they are heavy integration timings,
// not unit tests, so they get a generous timeout (the default 5s is too tight).
const PERF_TIMEOUT_MS = 120_000;

describe("rule performance", () => {
  it("no rule exceeds the absolute ms/1k-LOC budget", () => {
    for (const name of ruleNames) {
      const msPerKloc = (bestMs(name) / LOC) * 1000;
      expect(
        msPerKloc,
        `${name}: ${msPerKloc.toFixed(1)} ms/1k LOC exceeds ${ABSOLUTE_MS_PER_KLOC}`,
      ).toBeLessThan(ABSOLUTE_MS_PER_KLOC);
    }
  }, PERF_TIMEOUT_MS);

  it("no rule is an algorithmic outlier (>10x median)", () => {
    const timings = ruleNames.map((name) => ({ name, ms: bestMs(name) }));
    const sorted = [...timings].map((t) => t.ms).sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] ?? 0;
    const ceiling = median * RELATIVE_OUTLIER_FACTOR + RELATIVE_SLACK_MS;
    const slow = timings.filter((t) => t.ms > ceiling);
    expect(
      slow,
      `rules >${RELATIVE_OUTLIER_FACTOR}x median (${median.toFixed(2)}ms): ` +
        slow.map((t) => `${t.name}=${t.ms.toFixed(2)}ms`).join(", "),
    ).toHaveLength(0);
  }, PERF_TIMEOUT_MS);
});
