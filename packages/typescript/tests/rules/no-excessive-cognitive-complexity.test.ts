import { stripTypeScriptTypes } from "node:module";
import { runInNewContext } from "node:vm";
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { AST_NODE_TYPES } from "@typescript-eslint/utils";
import { ESLint, Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import plugin, { STRICT_RULES } from "../../src/index.js";
import rule, { functionComplexity, NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION } from "../../src/rules/no-excessive-cognitive-complexity.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

it.each([
  ["return value;", 0],
  ["for (slots[flag ? a : b] of items) {}", 2],
  ["if (a) { if (b) { return value; } }", 3],
  ["if (!a) return; if (!b) return; return value;", 2],
  ["if (a) {} else if (b) { if (c) {} } else { if (d) {} }", 7],
  ["if (a) {} else { if (b) {} }", 4],
  ["return a && b && c;", 1],
  ["return a && (b || c) && d;", 3],
  ["return (a && b) || (c && d);", 3],
  ["return a?.b ?? other?.c;", 0],
  ["return a ? b : c ? d : e;", 3],
  ["try { work(); } catch (error) { if (retry) work(); } finally { cleanup(); }", 3],
  ["for (const item of items) { if (item) continue; }", 3],
  ["for await (const item of items) { if (item) await work(); }", 3],
  ["for (let i = 0; i < 2; i++) { while (ready) { break; } }", 3],
  ["outer: do { if (ready) break outer; } while (again);", 4],
  ["switch (value) { case 1: break; default: if (ready) work(); }", 3],
  ["function inner() { if (ready) work(); } return inner;", 0],
  ["class Inner { method() { if (ready) work(); } } return Inner;", 0],
  ["return () => ready ? value : other;", 0],
  ["return recurse(value);", 0],
] as const)("scores function body %s as %i", (body, expected) => {
  const { ast, visitorKeys } = tsParser.parseForESLint(`async function sample() { ${body} }`, { loc: true, range: true });
  const fn = ast.body[0];
  if (fn?.type !== AST_NODE_TYPES.FunctionDeclaration) throw new Error("Expected a function fixture");
  expect(functionComplexity(fn, visitorKeys).reduce((sum, point) => sum + point.amount, 0)).toBe(expected);
});

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const TWENTY_ONE_GUARDS = "if (ready) work();".repeat(21);

it("ships an error under the public rule name and honors an exact inline exception", () => {
  const linter = new Linter();
  const config = {
    languageOptions: { parser: tsParser },
    plugins: { "@sarj": plugin },
    rules: { "@sarj/no-excessive-cognitive-complexity": STRICT_RULES["@sarj/no-excessive-cognitive-complexity"] },
  };
  const code = `function sample() { ${TWENTY_ONE_GUARDS} }`;
  const messages = linter.verify(code, config);
  expect(messages).toHaveLength(1);
  expect(messages[0]).toMatchObject({ ruleId: "@sarj/no-excessive-cognitive-complexity", severity: 2 });
  expect(linter.verify(`// eslint-disable-next-line @sarj/no-excessive-cognitive-complexity -- reviewed dispatch\n${code}`, config)).toEqual([]);
});

RULE_TESTER.run("no-excessive-cognitive-complexity", rule, {
  valid: [
    NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION.examples[1].files[0].source,
    `function sample() { ${"if (ready) work();".repeat(20)} }`,
    `function sample() { return ${Array<string>(600).fill("value").join("+")}; }`,
    { filename: "src/generated/sample.ts", code: `function sample() { ${TWENTY_ONE_GUARDS} }` },
    `// @generated\nfunction sample() { ${TWENTY_ONE_GUARDS} }`,
    `/* eslint-disable @rule-tester/no-excessive-cognitive-complexity -- tested separately by a reasoned exception */\nfunction sample() { ${TWENTY_ONE_GUARDS} }`,
  ],
  invalid: [
    { code: NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "excessiveComplexity", data: { score: 28, limit: 20, detail: "L1 +7 if; L1 +6 if; L1 +5 if" } }] },
    { code: `function sample() { ${TWENTY_ONE_GUARDS} }`, errors: [{ messageId: "excessiveComplexity", line: 1 }] },
    { filename: "tests/sample.test.ts", code: `function sample() { ${TWENTY_ONE_GUARDS} }`, errors: [{ messageId: "excessiveComplexity" }] },
    { code: `function outer() { function inner() { ${TWENTY_ONE_GUARDS} } } class Example { method() { ${TWENTY_ONE_GUARDS} } }`, errors: [{ messageId: "excessiveComplexity" }, { messageId: "excessiveComplexity" }] },
    { filename: "src/Screen.tsx", code: `function Screen() { ${TWENTY_ONE_GUARDS} return <div />; }`, languageOptions: { parserOptions: { ecmaFeatures: { jsx: true } } }, errors: [{ messageId: "excessiveComplexity" }] },
    { code: `const handler = () => { ${TWENTY_ONE_GUARDS} };`, errors: [{ messageId: "excessiveComplexity" }] },
  ],
});

const CONFIG = {
  languageOptions: { parser: tsParser },
  plugins: { "@sarj": plugin },
  rules: {
    "@sarj/no-excessive-cognitive-complexity": STRICT_RULES["@sarj/no-excessive-cognitive-complexity"],
  },
};

it.each([
  [20, []],
  [21, [{ ruleId: "@sarj/no-excessive-cognitive-complexity", severity: 2 }]],
  [25, [{ ruleId: "@sarj/no-excessive-cognitive-complexity", severity: 2 }]],
  [26, [{ ruleId: "@sarj/no-excessive-cognitive-complexity", severity: 2 }]],
] as const)("reports exactly the configured severity at score %i", (score, expected) => {
  const messages = new Linter().verify(`function sample() { ${"if (ready) work();".repeat(score)} }`, CONFIG);
  expect(messages.map(({ ruleId, severity }) => ({ ruleId, severity }))).toEqual(expected);
});

it("suppresses one function independently without hiding an error in another function", () => {
  const reviewed = `function review() { ${"if (ready) work();".repeat(21)} }`;
  const error = `function change() { ${"if (ready) work();".repeat(26)} }`;
  const messages = new Linter().verify(`// eslint-disable-next-line @sarj/no-excessive-cognitive-complexity -- reviewed
${reviewed}
${error}`, CONFIG);
  expect(messages).toHaveLength(1);
  expect(messages[0]).toMatchObject({ ruleId: "@sarj/no-excessive-cognitive-complexity", severity: 2 });
});

it("preserves error counts through the ESLint runner", async () => {
  const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: CONFIG });
  const [result] = await eslint.lintText(`function review() { ${"if (ready) work();".repeat(25)} } function change() { ${"if (ready) work();".repeat(26)} }`);
  expect(result).toMatchObject({ warningCount: 0, errorCount: 2, fixableWarningCount: 0, fixableErrorCount: 0 });
});


it.each([
  ["download-check-before", [21]],
  ["download-check-after", [6]],
  ["catalog-labels-before", [21]],
  ["catalog-labels-after", [3, 10]],
] as const)("keeps the published %s scores and findings accurate", (id, expected) => {
  const example = rule.documentation?.examples.find((item) => item.id === id);
  if (example === undefined) throw new Error(`Missing example ${id}`);
  const code = example.files[0]!.source;
  const { ast, visitorKeys } = tsParser.parseForESLint(code, { loc: true, range: true });
  const functions = ast.body.filter((node) => node.type === AST_NODE_TYPES.FunctionDeclaration);
  expect(functions.map((fn) => functionComplexity(fn, visitorKeys).reduce((sum, point) => sum + point.amount, 0))).toEqual(expected);
  expect(new Linter().verify(code, CONFIG)).toHaveLength(example.expectedCount);
});


it.each(["nested-decisions", "guard-decisions"])("preserves the last decision in %s", (id) => {
  const example = NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION.examples.find((item) => item.id === id);
  if (example === undefined) throw new Error(`Missing example ${id}`);
  const code = stripTypeScriptTypes(example.files[0].source);
  for (const lastCondition of [false, true]) {
    let calls = 0;
    runInNewContext(`${code}\ndecide(true, true, true, true, true, true, lastCondition);`, {
      lastCondition,
      act: () => { calls += 1; },
    });
    expect(calls).toBe(Number(lastCondition));
  }
});

it.each(["download-check-before", "download-check-after"])("preserves numeric eligibility in %s", (id) => {
  const example = NO_EXCESSIVE_COGNITIVE_COMPLEXITY_DOCUMENTATION.examples.find((item) => item.id === id);
  if (example === undefined) throw new Error(`Missing example ${id}`);
  const code = stripTypeScriptTypes(example.files[0].source);
  for (const [bytes, expected] of [[Number.NaN, false], [0, false], [1, true], [1000000, true], [1000001, false]] as const) {
    const result: unknown = runInNewContext(`${code}\ncanDownload(item);`, {
      item: { published: true, licensed: true, available: true, quarantined: false, bytes },
    });
    expect(result).toBe(expected);
  }
});
