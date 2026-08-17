import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/source-coupled-test.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const tester = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { sourceType: "module" } } });
const namedFs = "import { readFileSync } from 'node:fs';";
const fsObject = "import fs from 'node:fs';";

tester.run("source-coupled-test", rule, {
  valid: [
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('parsed', () => { const parsed = JSON.parse(readFileSync('policy.json', 'utf8')); expect(validate(parsed)).toEqual([]); });` },
    { filename: "/repo/render.test.ts", code: "test('render', () => { expect(render()).toContain('hello'); });" },
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('validator', () => { const source = readFileSync('main.tf', 'utf8'); expect(validate(source)).toEqual([]); });` },
    { filename: "/repo/policy.ts", code: `${namedFs} const source = readFileSync('main.tf', 'utf8'); expect(source).toContain('x');` },
    { filename: "/repo/unrelated.test.ts", code: "const source = client.readFile('main.tf'); expect(source).toContain('resource');" },
    { filename: "/repo/shadow.test.ts", code: `${namedFs} test('shadow', () => { const source = readFileSync('main.tf', 'utf8'); return () => { const source = render(); expect(source).toContain('resource'); }; });` },
    { filename: "/repo/shadow-reader.test.ts", code: `${namedFs} test('shadow', (readFileSync) => { const source = readFileSync('main.tf'); expect(source).toContain('resource'); });` },
    { filename: "/repo/shadow-fs.test.ts", code: `${fsObject} test('shadow', () => { const fs = client; const source = fs.readFileSync('main.tf'); expect(source).toContain('resource'); });` },
  ],
  invalid: [
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toMatch(/permissions/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.mjs", code: `${fsObject} test('raw', () => { const source = fs.readFileSync(new URL('./workflow.yml', import.meta.url), 'utf8'); assert.match(source, /permissions:/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('raw', () => { expect(readFileSync('workflow.yml', 'utf8').trim().includes('permissions')).toBe(true); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8').toString().slice(1); assert.ok(source.indexOf('permissions') >= 0); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source.match(/permissions/)).not.toBeNull(); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); assert(!source.includes('public')); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); assert.doesNotMatch(source, /public/); assert.ok(/permissions/.test(source)); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: "import { readFile } from 'node:fs/promises'; test('raw', async () => { const source = (await readFile('workflow.yml', 'utf8')).trim(); expect(source).toContain('permissions:'); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: "const { readFileSync: read } = require('fs'); test('raw', () => { assert.match(read('deploy.sh', 'utf8'), /curl/); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/loop.test.ts", code: `${namedFs} test('raw', () => { const files = ['deploy.sh', 'workflow.yml']; for (const file of files) { expect(readFileSync(file, 'utf8')).toMatch(/deploy|permissions/); } });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/closure.test.ts", code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); return () => { expect(source).toContain('permissions'); }; });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/two.test.ts", code: `${namedFs} test('source', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('x'); }); test('runtime', () => { const source = render(); expect(source).toContain('x'); });`, errors: [{ messageId: "rawSourceOracle" }] },
    {
      filename: "/repo/policy.test.mjs",
      code: `${namedFs} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('permissions'); expect(source).toMatch(/permissions/); });`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      filename: "/repo/independent.test.mjs",
      code: `${namedFs} test('raw', () => { const script = readFileSync('deploy.sh', 'utf8'); expect(script).toContain('deploy'); const workflow = readFileSync('workflow.yml', 'utf8'); expect(workflow).toContain('permissions:'); });`,
      errors: [{ messageId: "rawSourceOracle" }, { messageId: "rawSourceOracle" }],
    },
  ],
});
