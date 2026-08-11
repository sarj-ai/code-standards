import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/source-coupled-test.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const tester = new RuleTester({ languageOptions: { parser: tsParser } });

tester.run("source-coupled-test", rule, {
  valid: [
    { filename: "/repo/policy.test.ts", code: "test('parsed', () => { const parsed = JSON.parse(readFileSync('policy.json', 'utf8')); expect(validate(parsed)).toEqual([]); });" },
    { filename: "/repo/render.test.ts", code: "test('render', () => { expect(render()).toContain('hello'); });" },
    { filename: "/repo/policy.test.ts", code: "test('validator', () => { const source = readFileSync('main.tf', 'utf8'); expect(validate(source)).toEqual([]); });" },
    { filename: "/repo/policy.ts", code: "const source = readFileSync('main.tf', 'utf8'); expect(source).toContain('x');" },
  ],
  invalid: [
    { filename: "/repo/policy.test.ts", code: "test('raw', () => { const source = readFileSync('main.tf', 'utf8'); expect(source).toMatch(/prevent_destroy/); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.mjs", code: "test('raw', () => { const source = fs.readFileSync(new URL('./workflow.yml', import.meta.url), 'utf8'); assert.match(source, /permissions:/); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: "test('raw', () => { const source = readFileSync('main.tf', 'utf8'); expect(source.includes('prevent_destroy')).toBe(true); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/two.test.ts", code: "test('source', () => { const source = readFileSync('main.tf', 'utf8'); expect(source).toContain('x'); }); test('runtime', () => { const source = render(); expect(source).toContain('x'); });", errors: [{ messageId: "rawSourceOracle" }] },
    {
      filename: "/repo/policy.test.mjs",
      code: "test('raw', () => { const source = readFileSync('main.tf', 'utf8'); expect(source).toContain('resource'); expect(source).toMatch(/prevent_destroy/); });",
      errors: [{ messageId: "rawSourceOracle" }],
    },
  ],
});
