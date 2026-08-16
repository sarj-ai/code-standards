import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/iac-source-coupled-test.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const tester = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { sourceType: "module" } } });
const fsImport = "import { readFileSync } from 'node:fs';";

tester.run("iac-source-coupled-test", rule, {
  valid: [
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('plan', () => { const plan = JSON.parse(readFileSync('plan.json', 'utf8')); expect(validate(plan)).toEqual([]); });` },
    { filename: "/repo/policy.test.ts", code: "test('runtime', () => { expect(probeDeployment()).toEqual({ healthy: true }); });" },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('other source', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('permissions:'); });` },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('parsed length', () => { const plan = JSON.parse(readFileSync('plan.json', 'utf8')); expect(plan.resource_changes.length).toBeGreaterThan(0); });` },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('parsed split', () => { const plan = JSON.parse(readFileSync('plan.json', 'utf8')); expect(plan.address.split('.')).toHaveLength(2); });` },
    { filename: "/repo/policy.ts", code: `${fsImport} const source = readFileSync('main.tf', 'utf8'); expect(source).toContain('resource');` },
  ],
  invalid: [
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('raw', () => { const source = readFileSync('policy.tf', 'utf8'); expect(source).toMatch(/resource/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('raw', () => { const source = readFileSync('policy.hcl', 'utf8'); expect(source).toMatch(/resource/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('raw', () => { const source = readFileSync('policy.tfvars', 'utf8'); expect(source).toMatch(/resource/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('raw', () => { const source = readFileSync('policy.tf.json', 'utf8'); expect(source).toMatch(/resource/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('raw', () => { const source = readFileSync('policy.tftest.hcl', 'utf8'); expect(source).toMatch(/resource/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('raw', () => { const source = readFileSync('policy.tftest.json', 'utf8'); expect(source).toMatch(/resource/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('alias', () => { const path = new URL('./main.tf', import.meta.url); const source = readFileSync(path, 'utf8').toString().trim(); assert.ok(source.includes('resource')); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('regex', () => { const source = readFileSync('main.tf', 'utf8'); assert.ok(/resource/.test(source)); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('length', () => { const source = readFileSync('main.tf', 'utf8'); expect(source.length).toBeGreaterThan(0); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${fsImport} test('split', () => { const source = readFileSync('main.tf', 'utf8'); expect(source.split('\\n')).toContain('resource'); });`, errors: [{ messageId: "rawSourceOracle" }] },
  ],
});
