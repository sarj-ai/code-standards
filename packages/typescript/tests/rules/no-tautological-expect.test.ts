// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION,
} from "../../src/rules/no-tautological-expect.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

const TEST_FILE = "/repo/src/tests/dummy.test.ts";

RULE_TESTER.run("no-tautological-expect", rule, {
  valid: [
    ...([
      ["runtime result", "const value = read(); expect(value).toBe(true);"],
      ["mutable binding", "let value = true; run(); expect(value).toBe(true);"],
      ["mutable data", "const value = {ok: true}; run(value); expect(value).toEqual({ok: true});"],
      ["parameter shadows constant", "const value = true; function check(value: boolean) { expect(value).toBe(true); }"],
      ["destructured result", "const {value} = read(); expect(value).toBe(true);"],
      ["failing comparison", "const value = true; expect(value).toBe(false);"],
      ["failing matcher", "const value = null; expect(value).toBeUndefined();"],
      ["use before initialization", "expect(value).toBe(true); const value = true;"],
      ["custom expect", "const expect = custom; const value = true; expect(value).toBe(true);"],
      ["regexp", "const value = /x/; expect(value).toBeDefined();"],
    ] as const).map(([name, code]) => ({name, code, filename: TEST_FILE})),
    { filename: TEST_FILE, code: "expect(/x/).toBe(/x/);" },
    { filename: TEST_FILE, code: "expect(null).toBeUndefined();" },
    { filename: TEST_FILE, code: "expect([]).toBeFalsy();" },
    { filename: TEST_FILE, code: "expect(1).toBeNaN();" },
    { filename: TEST_FILE, code: "expect(false).toBeTruthy();" },
    { filename: TEST_FILE, code: "expect(+1n).toBe(+1n);" },
    { filename: TEST_FILE, code: "function check(expect) { expect(true).toBe(true); }" },
    {
      name: "allows determinism assertions on call results",
      filename: TEST_FILE,
      code: "it('hashes deterministically', () => { expect(hash([o])).toEqual(hash([o])); });",
    },
    {
      name: "allows reflexivity assertions on identifiers",
      filename: TEST_FILE,
      code: "it('is reflexive', () => { expect(a).toEqual(a); });",
    },
    {
      name: "allows memoization assertions on call results",
      filename: TEST_FILE,
      code: "it('memoizes', () => { expect(memo(x)).toBe(memo(x)); });",
    },
    {
      name: "allows stability assertions on member expressions",
      filename: TEST_FILE,
      code: "it('is stable', () => { expect(config.value).toBe(config.value); });",
    },
    {
      name: "allows a produced value compared with a literal",
      filename: TEST_FILE,
      code: NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "allows a literal compared with a produced value",
      filename: TEST_FILE,
      code: "it('returns one', () => { expect(1).toBe(result); });",
    },
    {
      name: "allows a zero-argument matcher on a produced value",
      filename: TEST_FILE,
      code: "it('is defined', () => { expect(result).toBeDefined(); });",
    },
    {
      name: "allows different literal values",
      filename: TEST_FILE,
      code: "it('is one', () => { expect(1).toBe(2); });",
    },
    {
      name: "allows equal literals with different source text",
      filename: TEST_FILE,
      code: "it('same value, different spelling', () => { expect(1).toBe(1.0); });",
    },
    {
      name: "allows a negated identical-literal comparison",
      filename: TEST_FILE,
      code: "it('negates', () => { expect(true).not.toBe(true); });",
    },
    {
      name: "allows a resolves chain with identical literals",
      filename: TEST_FILE,
      code: "it('resolves', async () => { await expect(1).resolves.toBe(1); });",
    },
    {
      name: "allows a rejects chain with identical literals",
      filename: TEST_FILE,
      code: "it('rejects', async () => { await expect(1).rejects.toBe(1); });",
    },
    {
      name: "allows array spreads that depend on runtime values",
      filename: TEST_FILE,
      code: "it('spreads', () => { expect([...xs]).toEqual([...xs]); });",
    },
    {
      name: "allows interpolated template literals",
      filename: TEST_FILE,
      code: "it('interpolates', () => { expect(`${id}`).toEqual(`${id}`); });",
    },
    {
      name: "allows object spreads that depend on runtime values",
      filename: TEST_FILE,
      code: "it('spreads an object', () => { expect({ ...base }).toBeTruthy(); });",
    },
    {
      name: "does not call distinct object references a passing tautology",
      filename: TEST_FILE,
      code: "it('compares references', () => { expect({ a: 1 }).toBe({ a: 1 }); });",
    },
    {
      name: "does not call distinct array references a passing tautology",
      filename: TEST_FILE,
      code: "it('compares references', () => { expect([1]).toBe([1]); });",
    },
    {
      name: "allows nested array values produced at runtime",
      filename: TEST_FILE,
      code: "it('keeps a value', () => { expect([value]).toEqual([value]); });",
    },
    {
      name: "allows nested object values produced at runtime",
      filename: TEST_FILE,
      code: "it('keeps a value', () => { expect({ value }).toEqual({ value }); });",
    },
    {
      name: "allows uninspected matchers",
      filename: TEST_FILE,
      code: "it('closes', () => { expect(0.1).toBeCloseTo(sum); });",
    },
    {
      name: "ignores calls not named expect",
      filename: TEST_FILE,
      code: "it('parses', () => { parser(true).toBe(true); });",
    },
    {
      name: "ignores expect calls outside test files",
      filename: "/repo/src/parser.ts",
      code: "export const check = () => expect(true).toBe(true);",
    },
  ],
  invalid: [
    ...([
      ["erased scalar setup", "const value = true as const; expect(value as boolean).toBe(true);", "tautologicalComparison"],
      ["bound boolean", "const value = true; expect(value).toBe(true);", "tautologicalComparison"],
      ["bound string", "const value = 'ok'; expect(value).toEqual('ok');", "tautologicalComparison"],
      ["scalar aliases", "const initial = 7; const value = initial; expect(value).toStrictEqual(initial);", "tautologicalComparison"],
      ["defined scalar", "const value = 7; expect(value).toBeDefined();", "tautologicalMatcher"],
      ["constant survives action", "const value = true; run(value); expect(value).toBeTruthy();", "tautologicalMatcher"],
    ] as const).map(([name, code, messageId]) => ({name, code, filename: TEST_FILE, errors: [{messageId}]})),
    {
      name: "reports a boolean placeholder assertion",
      filename: "/repo/apps/worker/test/handler.test.ts",
      code: [
        "it('disambiguates a customer record', () => {",
        "  expect(true).toBe(true); // placeholder",
        "});",
      ].join("\n"),
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports an identical boolean comparison",
      filename: TEST_FILE,
      code: NO_TAUTOLOGICAL_EXPECT_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports an identical number comparison",
      filename: TEST_FILE,
      code: "it('works', () => { expect(1).toEqual(1); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports toStrictEqual with identical literals",
      filename: TEST_FILE,
      code: "it('works', () => { expect('a').toStrictEqual('a'); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports identical array literals",
      filename: TEST_FILE,
      code: "it('works', () => { expect([1, 2]).toEqual([1, 2]); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports identical object literals",
      filename: TEST_FILE,
      code: "it('works', () => { expect({ a: 1 }).toEqual({ a: 1 }); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports identical signed numeric literals",
      filename: TEST_FILE,
      code: "it('works', () => { expect(-1).toBe(-1); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports identical static template literals",
      filename: TEST_FILE,
      code: "it('works', () => { expect(`fixed`).toEqual(`fixed`); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
    {
      name: "reports toBeDefined on a literal",
      filename: TEST_FILE,
      code: "it('works', () => { expect(true).toBeDefined(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      name: "reports toBeFalsy on null",
      filename: TEST_FILE,
      code: "it('works', () => { expect(null).toBeFalsy(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      name: "reports toBeTruthy on a literal",
      filename: TEST_FILE,
      code: "it('works', () => { expect('x').toBeTruthy(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      name: "reports toBeNull on a literal",
      filename: TEST_FILE,
      code: "it('works', () => { expect(null).toBeNull(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      name: "reports toBeFalsy on zero",
      filename: TEST_FILE,
      code: "it('works', () => { expect(0).toBeFalsy(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      name: "reports toBeTruthy on an array",
      filename: TEST_FILE,
      code: "it('works', () => { expect([1]).toBeTruthy(); });",
      errors: [{ messageId: "tautologicalMatcher" }],
    },
    {
      name: "reports each tautology in a test body",
      filename: TEST_FILE,
      code: [
        "it('placeholder suite', () => {",
        "  expect(true).toBe(true);",
        "  expect(1).toEqual(1);",
        "});",
      ].join("\n"),
      errors: [{ messageId: "tautologicalComparison" }, { messageId: "tautologicalComparison" }],
    },
    {
      name: "reports files in a tests directory without a test suffix",
      filename: "/repo/src/tests/dummy.ts",
      code: "it('works', () => { expect(true).toBe(true); });",
      errors: [{ messageId: "tautologicalComparison" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "literal-only-assertion-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/add.test.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/add.test.ts",
        "source": "it('works', () => { expect(true)[\"toBe\"](true); });"
      }
    ]
  },
  {
    "id": "literal-only-assertion-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/add.test.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/add.test.ts",
        "source": "it('works', () => { expect(true)[auditDynamicMember](true); });"
      }
    ]
  }
] } });
});
