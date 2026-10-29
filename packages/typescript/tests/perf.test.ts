












































import { Linter, type SourceCode } from "eslint";
import { threadCpuUsage } from "node:process";
import * as tsParser from "@typescript-eslint/parser";
import { describe, expect, it } from "vitest";

import plugin from "../src/index.js";



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








const MAX_RULE_COST_VS_PARSE = 0.25;
const RELATIVE_OUTLIER_FACTOR = 10;







const RELATIVE_SLACK_VS_PARSE = 0.01;

const RULE_NAMES = Object.keys(plugin.rules);

const LINTER = new Linter();

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

function threadCpuMs(run: () => void): number {
  const start = threadCpuUsage();
  run();
  const { user, system } = threadCpuUsage(start);
  return (user + system) / 1000;
}

function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? 0;
}








LINTER.verify(SOURCE, NO_RULES, "synthetic.tsx");
const PARSED: SourceCode = LINTER.getSourceCode();

const RULE_SAMPLES = new Map(RULE_NAMES.map((name) => [name, [] as number[]]));
const RATIO_SAMPLES = new Map(RULE_NAMES.map((name) => [name, [] as number[]]));
const PARSE_SAMPLES: number[] = [];
const MEASUREMENT_ROUNDS = 7;

for (const name of RULE_NAMES) {
  LINTER.verify(PARSED, configFor({ [`@sarj/${name}`]: "error" }), "synthetic.tsx");
}

for (let round = 0; round < MEASUREMENT_ROUNDS; round++) {
  const parseBefore = threadCpuMs(() => LINTER.verify(SOURCE, NO_RULES, "synthetic.tsx"));
  const offset = round % RULE_NAMES.length;
  const orderedNames = [...RULE_NAMES.slice(offset), ...RULE_NAMES.slice(0, offset)];
  const roundSamples = new Map<string, number>();

  for (const name of orderedNames) {
    const config = configFor({ [`@sarj/${name}`]: "error" });
    roundSamples.set(
      name,
      threadCpuMs(() => LINTER.verify(PARSED, config, "synthetic.tsx")),
    );
  }

  const parseAfter = threadCpuMs(() => LINTER.verify(SOURCE, NO_RULES, "synthetic.tsx"));
  const roundParseMs = (parseBefore + parseAfter) / 2;
  PARSE_SAMPLES.push(roundParseMs);
  for (const [name, milliseconds] of roundSamples) {
    RULE_SAMPLES.get(name)?.push(milliseconds);
    RATIO_SAMPLES.get(name)?.push(milliseconds / roundParseMs);
  }
}

const PARSE_MS = median(PARSE_SAMPLES);
const CONFIRMATION_ROUNDS = 9;

function ruleMs(ruleName: string): number {
  return median(RULE_SAMPLES.get(ruleName) ?? []);
}

function ruleRatio(ruleName: string): number {
  return median(RATIO_SAMPLES.get(ruleName) ?? []);
}

function confirmedRuleRatio(ruleName: string): number {
  const config = configFor({ [`@sarj/${ruleName}`]: "error" });
  const ratios = Array.from({ length: CONFIRMATION_ROUNDS }, () => {
    const parseBefore = threadCpuMs(() => LINTER.verify(SOURCE, NO_RULES, "synthetic.tsx"));
    const rule = threadCpuMs(() => LINTER.verify(PARSED, config, "synthetic.tsx"));
    const parseAfter = threadCpuMs(() => LINTER.verify(SOURCE, NO_RULES, "synthetic.tsx"));
    return rule / ((parseBefore + parseAfter) / 2);
  });
  return median(ratios);
}

const PERF_TIMEOUT_MS = 120_000;

describe("rule performance", () => {
  it("excludes blocked time instead of charging it to the rule", () => {
    const start = performance.now();
    const cpuMs = threadCpuMs(() => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 40));
    const wallMs = performance.now() - start;
    expect(wallMs).toBeGreaterThanOrEqual(30);
    expect(cpuMs).toBeLessThan(wallMs * MAX_RULE_COST_VS_PARSE);
  });

  it("still rejects CPU work exceeding the unchanged parser-relative budget", () => {
    const targetCpuMs = Math.max(5, PARSE_MS * MAX_RULE_COST_VS_PARSE * 2);
    let checksum = 0;
    const measured = threadCpuMs(() => {
      const start = threadCpuUsage();
      while (true) {
        for (let index = 0; index < 1000; index++) checksum += index;
        const { user, system } = threadCpuUsage(start);
        if ((user + system) / 1000 >= targetCpuMs) break;
      }
    });
    expect(checksum).toBeGreaterThan(0);
    expect(measured / PARSE_MS).toBeGreaterThan(MAX_RULE_COST_VS_PARSE);
  });

  it("parses once and measures the rules, not the parser", () => {




    expect(PARSE_MS, "parse of the synthetic source did not register").toBeGreaterThan(1);
    const worstRatio = Math.max(...RULE_NAMES.map((name) => ruleRatio(name)));
    expect(
      worstRatio,
      `slowest rule is ${worstRatio.toFixed(3)}x the parse — timings look like parse timings`,
    ).toBeLessThan(0.5);
  }, PERF_TIMEOUT_MS);

  it("no rule costs more than a fraction of parsing the same file", () => {
    for (const name of RULE_NAMES) {
      const initialRatio = ruleRatio(name);
      const ratio =
        initialRatio < MAX_RULE_COST_VS_PARSE ? initialRatio : confirmedRuleRatio(name);
      expect(
        ratio,
        `${name}: ${ratio.toFixed(4)}x the parse cost of the same file after confirmation ` +
          `(initial ${initialRatio.toFixed(4)}, budget ${MAX_RULE_COST_VS_PARSE})`,
      ).toBeLessThan(MAX_RULE_COST_VS_PARSE);
    }
  }, PERF_TIMEOUT_MS);

  it("no rule is an algorithmic outlier (>10x median)", () => {
    const initial = RULE_NAMES.map((name) => ({ name, ms: ruleMs(name) }));
    const initialSorted = [...initial].map((timing) => timing.ms).sort((a, b) => a - b);
    const initialMedian = initialSorted[Math.floor(initialSorted.length / 2)] ?? 0;
    const initialCeiling =
      initialMedian * RELATIVE_OUTLIER_FACTOR + PARSE_MS * RELATIVE_SLACK_VS_PARSE;
    const timings = initial.map((timing) => {
      if (timing.ms <= initialCeiling) return timing;
      const config = configFor({ [`@sarj/${timing.name}`]: "error" });
      const confirmation = Array.from({ length: 5 }, () =>
        threadCpuMs(() => {
          LINTER.verify(PARSED, config, "synthetic.tsx");
        }),
      );
      return {
        name: timing.name,
        ms: median([...(RULE_SAMPLES.get(timing.name) ?? []), ...confirmation]),
      };
    });
    const sorted = [...timings].map((t) => t.ms).sort((a, b) => a - b);
    const medianMs = sorted[Math.floor(sorted.length / 2)] ?? 0;
    const ceiling = medianMs * RELATIVE_OUTLIER_FACTOR + PARSE_MS * RELATIVE_SLACK_VS_PARSE;
    const slow = timings.filter((t) => t.ms > ceiling);
    expect(
      slow,
      `rules >${RELATIVE_OUTLIER_FACTOR}x median (${medianMs.toFixed(2)}ms): ` +
        slow.map((t) => `${t.name}=${t.ms.toFixed(2)}ms`).join(", "),
    ).toHaveLength(0);
  }, PERF_TIMEOUT_MS);
});
