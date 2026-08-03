/**
 * Rule performance gates.
 *
 * ## What was wrong with the old shape
 *
 * Every timing was `linter.verify(SOURCE_TEXT, …)`, which PARSES the 1,800-line
 * source before running the rule. Measured on this machine: the parse costs
 * ~120 ms idle and ~305 ms under six-way load, while the rule itself costs
 * 0.3-4 ms. So 97-99% of every "rule timing" was the TypeScript parser, and:
 *
 * - the absolute `ms/1k LOC` budget was a gate on the parser's speed, not on any
 *   rule. `enforce-file-structure` was measured at 314-337 ms/1k LOC against a
 *   200 ms budget while a corpus sweep ran on the other cores, and passed in
 *   isolation — the rule had not changed by a microsecond;
 * - the "10x the median" outlier gate compared numbers that were all
 *   `parse + epsilon`, so it could not have caught a rule 10x slower than its
 *   peers. It was arithmetic on a constant.
 *
 * A wall-clock budget that fails on a busy CI runner does not get fixed, it gets
 * ignored — so it is fixed here rather than raised.
 *
 * ## What it does now
 *
 * The source is parsed ONCE and the resulting `SourceCode` is handed to every
 * `verify` call, which skips the parser. What is left is the rule. The whole
 * file now runs in ~2 s instead of ~60 s, and the numbers mean what they say.
 *
 * Both gates are RATIOS measured in the same process, in the same run:
 *
 * - the absolute-style backstop is "a single rule must cost less than
 *   `MAX_RULE_COST_VS_PARSE` of what parsing the same file costs". Load and
 *   hardware move the numerator and the denominator together, so the ratio is
 *   stable — measured at 0.006-0.018 idle and under six-way load alike;
 * - the outlier gate is unchanged in spirit: no rule may exceed
 *   `RELATIVE_OUTLIER_FACTOR` times the median rule, which now compares rule
 *   costs rather than parse costs. Worst observed is ~2.8x.
 */

import { Linter, type SourceCode } from "eslint";
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

/**
 * A rule may cost at most this fraction of what parsing the same file costs.
 * Worst measured is 0.018, so the gate has ~8x headroom: it is a catastrophe
 * detector, not a target.
 */
const MAX_RULE_COST_VS_PARSE = 0.15;
const RELATIVE_OUTLIER_FACTOR = 10;

/**
 * Absolute floor on the outlier ceiling, as a fraction of the SAME parse
 * measurement. It exists so that a registry of uniformly trivial rules cannot
 * collapse the ceiling onto the timer's own resolution; expressing it against
 * the parse keeps it load-proportional like everything else here.
 */
const RELATIVE_SLACK_VS_PARSE = 0.01;

const ruleNames = Object.keys(plugin.rules);

const linter = new Linter();

function configFor(rules: Linter.RulesRecord): Linter.Config[] {
  return [
    {
      files: ["**/*.tsx"],
      languageOptions: {
        parser: tsParser,
        parserOptions: { ecmaFeatures: { jsx: true }, sourceType: "module" },
      },
      plugins: { "@sarj": plugin as unknown as Record<string, unknown> },
      rules,
    },
  ];
}

const NO_RULES = configFor({});

function elapsedMs(run: () => void): number {
  const start = performance.now();
  run();
  return performance.now() - start;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}

/**
 * The denominator: what it costs to parse `SOURCE` once, with no rules running.
 * Measured here, in this process, next to the rule timings, so it carries the
 * same machine speed and the same background load.
 */
// Parsed once. Handing `verify` a `SourceCode` is what takes the parser out of
// every subsequent measurement.
linter.verify(SOURCE, NO_RULES, "synthetic.tsx");
const parsed: SourceCode = linter.getSourceCode();

const ruleSamples = new Map(ruleNames.map((name) => [name, [] as number[]]));
const ratioSamples = new Map(ruleNames.map((name) => [name, [] as number[]]));
const parseSamples: number[] = [];
const MEASUREMENT_ROUNDS = 7;

for (const name of ruleNames) {
  linter.verify(parsed, configFor({ [`@sarj/${name}`]: "error" }), "synthetic.tsx");
}

for (let round = 0; round < MEASUREMENT_ROUNDS; round++) {
  const parseBefore = elapsedMs(() => linter.verify(SOURCE, NO_RULES, "synthetic.tsx"));
  const offset = round % ruleNames.length;
  const orderedNames = [...ruleNames.slice(offset), ...ruleNames.slice(0, offset)];
  const roundSamples = new Map<string, number>();

  for (const name of orderedNames) {
    const config = configFor({ [`@sarj/${name}`]: "error" });
    roundSamples.set(
      name,
      elapsedMs(() => linter.verify(parsed, config, "synthetic.tsx")),
    );
  }

  const parseAfter = elapsedMs(() => linter.verify(SOURCE, NO_RULES, "synthetic.tsx"));
  const roundParseMs = (parseBefore + parseAfter) / 2;
  parseSamples.push(roundParseMs);
  for (const [name, milliseconds] of roundSamples) {
    ruleSamples.get(name)?.push(milliseconds);
    ratioSamples.get(name)?.push(milliseconds / roundParseMs);
  }
}

const parseMs = median(parseSamples);

function ruleMs(ruleName: string): number {
  return median(ruleSamples.get(ruleName) ?? []);
}

function ruleRatio(ruleName: string): number {
  return median(ratioSamples.get(ruleName) ?? []);
}

const PERF_TIMEOUT_MS = 120_000;

describe("rule performance", () => {
  it("parses once and measures the rules, not the parser", () => {
    // Guard on the measurement itself: if a future refactor goes back to handing
    // `verify` a string, every timing silently becomes a parse timing again and
    // both gates below stop meaning anything. A rule cannot plausibly cost as
    // much as a full parse.
    expect(parseMs, "parse of the synthetic source did not register").toBeGreaterThan(1);
    const worstRatio = Math.max(...ruleNames.map((name) => ruleRatio(name)));
    expect(
      worstRatio,
      `slowest rule is ${worstRatio.toFixed(3)}x the parse — timings look like parse timings`,
    ).toBeLessThan(0.5);
  }, PERF_TIMEOUT_MS);

  it("no rule costs more than a fraction of parsing the same file", () => {
    for (const name of ruleNames) {
      const ratio = ruleRatio(name);
      expect(
        ratio,
        `${name}: ${ratio.toFixed(4)}x the parse cost of the same file (budget ${MAX_RULE_COST_VS_PARSE})`,
      ).toBeLessThan(MAX_RULE_COST_VS_PARSE);
    }
  }, PERF_TIMEOUT_MS);

  it("no rule is an algorithmic outlier (>10x median)", () => {
    const timings = ruleNames.map((name) => ({ name, ms: ruleMs(name) }));
    const sorted = [...timings].map((t) => t.ms).sort((a, b) => a - b);
    const median = sorted[Math.floor(sorted.length / 2)] ?? 0;
    const ceiling = median * RELATIVE_OUTLIER_FACTOR + parseMs * RELATIVE_SLACK_VS_PARSE;
    const slow = timings.filter((t) => t.ms > ceiling);
    expect(
      slow,
      `rules >${RELATIVE_OUTLIER_FACTOR}x median (${median.toFixed(2)}ms): ` +
        slow.map((t) => `${t.name}=${t.ms.toFixed(2)}ms`).join(", "),
    ).toHaveLength(0);
  }, PERF_TIMEOUT_MS);
});
