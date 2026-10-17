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
      ["keeps independent result bindings", "const before=operation(); const after=operation(); expect(before).toBe(after);"],
      ["keeps repeated property and getter reads", "const result=operation(); expect(result.value).toBe(result.value);"],
      ["keeps mutable binding identity unproven", "let result=operation(); expect(result).toBe(result);"],
      ["keeps imported live identity unproven", "import {result} from './state'; expect(result).toBe(result);"],
      ["keeps parameter identity outside the const proof", "function check(result) {expect(result).toBe(result);}"],
      ["keeps deep equality reflexivity contracts", "const result=operation(); expect(result).toEqual(result);"],
      ["keeps a failing negative identity assertion", "const result=operation(); expect(result).not.toBe(result);"],
      ["keeps customized identity semantics", "expect.extend({toBe:custom}); const result=operation(); expect(result).toBe(result);"],
      ["keeps captured identity matcher contracts", "const result=operation(); expect(()=>expect(result).toBe(result)).not.toThrow();"],
      ["keeps forward identity references unproven", "expect(result).toBe(result); const result=operation();"],
      ["keeps reassigned const identity unproven", "const result=operation(); result=other; expect(result).toBe(result);"],
      ["keeps destructured binding identity outside the proof", "const {result}=operation(); expect(result).toBe(result);"],
    ] as const).map(([name, code]) => ({name, code, filename: TEST_FILE})),
    ...([
      ["retains a replaced built-in matcher contract", "import {expect} from 'vitest'; expect.extend({toBe: () => ({pass: false, message: () => 'changed'})}); expect(true).toBe(true);"],
      ["retains a replaced zero-argument matcher", "import {expect as verify} from 'vitest'; verify['extend']({['toBeTruthy']: () => ({pass: false, message: () => 'changed'})}); verify(true).toBeTruthy();"],
      ["keeps opaque matcher registrations unproven", "import {expect} from 'vitest'; expect.extend(matchers); expect(true).toBe(true);"],
      ["keeps spread matcher registrations unproven", "expect.extend({...matchers}); expect(true).toBe(true);"],
      ["keeps dynamic matcher registrations unproven", "expect.extend({[name]: custom}); expect(true).toBe(true);"],
      ["retains nonempty custom deep equality testers", "import {expect} from 'vitest'; expect.addEqualityTesters([custom]); expect({ok:true}).toEqual({ok:true});"],
      ["retains opaque custom strict equality testers", "import {expect} from '@jest/globals'; expect.addEqualityTesters(testers); expect(true).toStrictEqual(true);"],
      ["retains direct passing matcher exception contracts", "import {expect} from 'vitest'; expect(() => expect(true).toBe(true)).not.toThrow();"],
      ["retains block callback assertion contracts", "import {expect as verify} from 'vitest'; verify(() => { verify(false).not.toBeTruthy(); }).not.toThrowError();"],
      ["retains erased callback exception contracts", "expect(((() => expect(true).toBe(true)) as () => void)).not.toThrow();"],
      ["retains exception snapshot contracts", "expect(() => expect(true).toBe(true)).toThrowErrorMatchingInlineSnapshot('message');"],
      ["retains static diagnostic messages on produced values", "import {expect} from 'vitest'; expect(read(), 'ready').toBe(true);"],
      ["retains failing assertions with diagnostic messages", "import {expect} from 'vitest'; expect(false, 'ready').toBe(true);"],
      ["retains runtime diagnostic effects", "import {expect} from 'vitest'; expect(true, buildDiagnostic()).toBe(true);"],
      ["keeps unsupported Jest message overload opaque", "import {expect} from '@jest/globals'; expect(true, 'ready').toBe(true);"],
      ["keeps unknown global message overload opaque", "expect(true, 'ready').toBe(true);"],
      ["retains message representation contracts", "import {expect} from 'vitest'; expect(1, 'ready').toBe(1.0);"],
      ["keeps a type-only message assertion unproven", "import type {expect} from 'vitest'; expect(true, 'ready').toBe(true);"],
      ["keeps shadowed message assertion bindings unproven", "import {expect} from 'vitest'; function contract(expect) {expect(true, 'ready').toBe(true);}"],
      ["retains captured snapshot state", "import {expect} from 'vitest'; const before = read(); act(); expect(before, 'captured').toEqual(read());"],
    ] as const).map(([name, code]) => ({name, code, filename: TEST_FILE})),
    { name: "preserves exact-code explained suppression for a setup assertion", filename: TEST_FILE, code: "// eslint-disable-next-line @rule-tester/no-tautological-expect -- assertion extension contract is under test\nexpect(false).not.toBeTruthy();" },
    { name: "keeps failing literal assertions after unwrapping", filename: TEST_FILE, code: 'expect((false as const)).toBe((true as const));' },
    { name: "preserves structural identity checks after unwrapping", filename: TEST_FILE, code: 'expect(([] as const)).toBe(([] as const));' },
    { name: "keeps asserted dynamic results opaque", filename: TEST_FILE, code: 'expect((read() as boolean)).toBe((true as const));' },
    { name: "keeps distinct literal representations after unwrapping", filename: TEST_FILE, code: 'expect((1 as const)).toBe((1.0 as const));' },

    ...([
      ["failing negated matcher", "expect(true).not.toBeTruthy();"],
      ["failing negated null matcher", "expect(null).not.toBeNull();"],
      ["runtime negated matcher", "expect(read()).not.toBeNull();"],
      ["local alias", "const verify = custom; verify(false).not.toBeTruthy();"],
      ["shadowed imported alias", "import {expect as verify} from 'vitest'; function check(verify) { verify(false).not.toBeTruthy(); }"],
      ["type-only import", "import type {expect} from 'vitest'; expect(true).toBeTruthy();"],
      ["type-only alias", "import {type expect as verify} from 'vitest'; verify(false).not.toBeTruthy();"],
      ["foreign expect export", "import {expect} from './helpers'; expect(true).toBeTruthy();"],
      ["namespace import", "import * as runner from 'vitest'; runner.expect(false).not.toBeTruthy();"],
      ["async negated chain", "expect(false).resolves.not.toBeTruthy();"],
      ["async modifier after negation", "expect(false).not.resolves.toBeTruthy();"],
      ["dynamic negation", "expect(false)[modifier].toBeTruthy();"],
      ["dynamic negated matcher", "expect(false).not[matcher]();"],
      ["multiple negations", "expect(false).not.not.toBeTruthy();"],
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
    { name: "assigned configured global", filename: TEST_FILE, languageOptions: { globals: { expect: "writable" } }, code: "expect = custom; expect(true).toBeTruthy();" },
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
      ["reports self identity of a produced result", "const result=operation(); expect(result).toBe(result);"],
      ["reports self identity of a produced object", "const result={value:read()}; expect(result).toBe(result);"],
      ["reports NaN self identity", "const result=Number.NaN; expect(result).toBe(result);"],
      ["reports erased self identity with a diagnostic alias", "import {expect as verify} from 'vitest'; const result=operation(); verify(result as unknown,'observed').toBe(result!);"],
      ["reports literal const self identity once", "const result=true; expect(result).toBe(result);"],
    ] as const).map(([name, code]) => ({name, code, filename: TEST_FILE, errors: [{messageId: "tautologicalComparison" as const}]})),
    ...([
      ["reports Vitest static-message literal comparisons", "import {expect} from 'vitest'; expect(true, 'ready').toBe(true);", "tautologicalComparison"],
      ["reports an imported alias with a const diagnostic", "import {expect as verify} from 'vitest'; const note='ready'; verify(false, note).not.toBeTruthy();", "tautologicalMatcher"],
      ["reports Playwright static-message literal comparisons", "import {expect} from '@playwright/test'; expect(1, `ready`).toEqual(1);", "tautologicalComparison"],
      ["keeps unrelated matcher extensions from hiding built-in tautologies", "import {expect} from 'vitest'; expect.extend({toBeReady: custom}); expect(true).toBe(true);", "tautologicalComparison"],
      ["keeps custom deep testers from hiding identity tautologies", "import {expect} from 'vitest'; expect.addEqualityTesters([custom]); expect(true).toBe(true);", "tautologicalComparison"],
      ["keeps empty equality testers from hiding deep tautologies", "expect.addEqualityTesters([]); expect({ok:true}).toEqual({ok:true});", "tautologicalComparison"],
      ["keeps shadowed matcher registrations from changing framework semantics", "import {expect} from 'vitest'; function register(expect) {expect.extend({toBe:custom});} expect(true).toBe(true);", "tautologicalComparison"],
      ["keeps arbitrary helper callbacks checked", "helper(() => expect(true).toBe(true));", "tautologicalComparison"],
      ["keeps uninvoked callbacks checked", "const run = () => expect(true).toBe(true);", "tautologicalComparison"],
      ["keeps custom outer expectations from claiming exception contracts", "import {expect} from 'vitest'; custom(() => expect(true).toBe(true)).not.toThrow();", "tautologicalComparison"],
      ["keeps async callbacks outside synchronous throw contracts", "expect(async () => expect(true).toBe(true)).not.toThrow();", "tautologicalComparison"],
    ] as const).map(([name, code, messageId]) => ({name, code, filename: TEST_FILE, errors: [{messageId}]})),
    { name: "retains identical literal assertions through const assertions", filename: TEST_FILE, code: 'expect((true as const)).toBe((true as const));', errors: [{ messageId: "tautologicalComparison" }] },
    { name: "recognizes static computed literal matchers", filename: TEST_FILE, code: 'expect(true)["toBe"](true);', errors: [{ messageId: "tautologicalComparison" }] },
    { name: "retains literal zero-argument matcher proofs through erased wrappers", filename: TEST_FILE, code: 'expect((true satisfies boolean)).toBeTruthy();', errors: [{ messageId: "tautologicalMatcher" }] },

    ...([
      ["negated literal truthiness", "expect(false).not.toBeTruthy();", "tautologicalMatcher"],
      ["negated literal falsiness", "expect(true).not.toBeFalsy();", "tautologicalMatcher"],
      ["negated literal null check", "expect(0).not.toBeNull();", "tautologicalMatcher"],
      ["negated literal undefined check", "expect('ok').not.toBeUndefined();", "tautologicalMatcher"],
      ["negated literal NaN check", "expect(3).not.toBeNaN();", "tautologicalMatcher"],
      ["negated const setup", "const value = null; expect(value).not.toBeTruthy();", "tautologicalMatcher"],
      ["negated array setup", "expect([]).not.toBeFalsy();", "tautologicalMatcher"],
      ["negated matcher through erased wrappers", "expect((false as const))['not']['toBeTruthy']();", "tautologicalMatcher"],
      ["imported expectation alias", "import {expect as verify} from 'vitest'; verify(true).toBe(true);", "tautologicalComparison"],
      ["negated imported alias", "import {expect as verify} from '@jest/globals'; verify(false).not.toBeTruthy();", "tautologicalMatcher"],
      ["Bun expectation alias", "import {expect as verify} from 'bun:test'; verify(null).toBeNull();", "tautologicalMatcher"],
      ["Playwright expectation alias", "import {expect as verify} from '@playwright/test'; verify('ok').not.toBeUndefined();", "tautologicalMatcher"],
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
