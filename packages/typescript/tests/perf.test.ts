import { performance } from "node:perf_hooks";
import { expect, it } from "vitest";
import plugin from "../src/index.js";
import { ruleReports } from "./_native-rule.js";

const source = (count: number): string => Array.from({ length: count }, (_, index) =>
  `function handler${index}(items: string[]) { let text = ''; for (const item of items) text += item; try { run(); } catch (error) { console.error(error); } return text; }`).join("\n");

const SMALL = source(40);
const LARGE = source(80);

it("every registered rule runs on the native host with a nontrivial source file", () => {
  for (const rule of Object.values(plugin.rules)) ruleReports(rule, LARGE);
});

it.each(["no-excessive-cognitive-complexity", "no-string-concat-in-loop", "stepdown"] as const)(
  "%s avoids a severe superlinear regression when the source doubles", (name) => {
    const rule = plugin.rules[name];
    const median = (code: string): number => {
      const samples: number[] = [];
      for (let index = 0; index < 7; index += 1) {
        const start = performance.now();
        ruleReports(rule, code);
        samples.push(performance.now() - start);
      }
      samples.sort((a, b) => a - b);
      return samples[3] ?? 0;
    };
    ruleReports(rule, SMALL);
    expect(median(LARGE)).toBeLessThan(median(SMALL) * 8 + 5);
  },
);
