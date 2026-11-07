// vitest: shared-module-graph
import rule from "../../src/rules/no-mutating-container-transform.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

TESTER.run("no-mutating-container-transform", rule, {
  valid: [
    "function ordered(values: number[]): number[] { const result = [...values]; result.sort(); return result; }",
    { name: "explicit command", code: "function ordered(values: number[]): void { values.sort(); }" },
    { name: "scalar command result", code: "function append(values: number[]): number { return values.push(1); }" },
    { name: "array read", code: "function first(values: number[]): number[] { return values.slice(1); }" },
    { name: "copy then sort", code: "function order(values: number[]): number[] { values = [...values]; values.sort(); return values; }" },
    { name: "alias rebound to copy", code: "function order(values: number[]): number[] { let result = values; result = values.slice(); result.sort(); return result; }" },
    { name: "literal false branch", code: "function order(values: number[]): number[] { if (false) { values.sort(); } return values; }" },
    { name: "short circuit never mutates", code: "function order(values: number[]): number[] { false && values.sort(); return values; }" },
    { name: "truthy short circuit never mutates", code: "function order(values: number[]): number[] { true || values.sort(); return values; }" },
    { name: "unselected conditional never mutates", code: "function order(values: number[]): number[] { false ? values.sort() : values.slice(); return values; }" },
    { name: "unreachable mutation", code: "function order(values: number[]): number[] { return [...values]; values.sort(); }" },
    { name: "deferred callback", code: "function order(values: number[]): number[] { register(() => values.sort()); return [...values]; }" },
    { name: "scope shadow", code: "function order(values: number[]): number[] { { const values: number[] = []; values.sort(); } return values; }" },
    { name: "unknown array implementation", code: "function order(values: DomainValues): number[] { values.sort(); return values.list(); }" },
    { name: "custom Array contract", code: "interface Array<T> { sort(): void; } function order(values: Array<number>): Array<number> { values.sort(); return values; }" },
    { name: "generic array element", code: "function order<T>(values: T[]): T[] { values.sort(); return values; }" },
    { name: "unsupported loop contract", code: "function order(values: number[]): number[] { for (const value of values) { values.push(value); } return values; }" },
    { name: "generated artifact", filename: "src/order.generated.ts", code: "function ordered(values: number[]): number[] { values.sort(); return values; }" },
  ],
  invalid: [
    { name: "local suppression still reports (valid under ESLint; Oxlint's RuleTester does not apply disable directives)", code: "function order(values: number[]): number[] {\n// eslint-disable-next-line @rule-tester/no-mutating-container-transform -- library contract is explicitly in-place\nvalues.sort(); return values; }", errors: [{ messageId: "borrowedMutation" }] },
    { code: "function ordered(values: number[]): number[] { values.sort(); return values; }", errors: [{ messageId: "borrowedMutation" }] },
    ...[
      ["direct alias", "function order(values: number[]): number[] { const result = values; result.reverse(); return result; }"],
      ["copying after mutation", "function order(values: number[]): number[] { values.sort(); return [...values]; }"],
      ["item write", "function order(values: number[]): number[] { values[0] = 2; return values; }"],
      ["item update", "function order(values: number[]): number[] { values[0]++; return values; }"],
      ["item deletion", "function order(values: number[]): number[] { delete values[0]; return values; }"],
      ["length write", "function order(values: number[]): number[] { values.length = 0; return values; }"],
      ["async transform", "async function order(values: Array<number>): Promise<number[]> { values.push(1); return values; }"],
      ["arrow transform", "const order = (values: string[]): string[] => { values.sort(); return values; };"],
      ["literal true branch", "function order(values: number[]): number[] { if (true) { values.sort(); } return values; }"],
      ["conditional mutation", "function order(values: number[], enabled: boolean): number[] { if (enabled) { values.sort(); } return values; }"],
      ["alias survives source rebind", "function order(values: number[]): number[] { const original = values; values = []; original.sort(); return values; }"],
      ["one finding per transform", "function order(values: number[]): number[] { values.sort(); values.push(1); return values; }"],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "borrowedMutation" as const }] })),
  ],
});
