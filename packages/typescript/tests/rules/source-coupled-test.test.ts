import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/source-coupled-test.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { sourceType: "module" } } });
const NAMED_FS = "import { readFileSync } from 'node:fs';";
const FS_OBJECT = "import fs from 'node:fs';";

TESTER.run("source-coupled-test", rule, {
  valid: [
    { name: "does not infer iterator-pipeline assertion dataflow", filename: "/repo/config.test.ts", code: `${NAMED_FS} import { fileURLToPath } from 'node:url'; test('raw', () => { const source = readFileSync(fileURLToPath(new URL('../wrangler.jsonc', import.meta.url)), 'utf8'); const values = source.matchAll(/NEXT_PUBLIC_ENVIRONMENT/g).map((match) => match[0]).toArray(); expect(values).toEqual(['dev']); });` },
    { name: "does not leak block-local source provenance", filename: "/repo/policy.test.ts", code: `${NAMED_FS} const source = 'runtime'; { const source = readFileSync('workflow.yml', 'utf8'); } expect(source).toContain('x');` },
    { name: "checks the complete concatenated path suffix", filename: "/repo/policy.test.ts", code: `${NAMED_FS} expect(readFileSync('workflow.yml' + '.log', 'utf8')).toContain('x');` },
    { name: "does not infer an arbitrary path factory", filename: "/repo/policy.test.ts", code: `${NAMED_FS} expect(readFileSync(logPathFor('workflow.yml'), 'utf8')).toContain('x');` },
    { name: "does not overlook uninitialized shadow bindings", filename: "/repo/policy.test.ts", code: `${NAMED_FS} const source = readFileSync('workflow.yml', 'utf8'); { let source; expect(source).toContain('x'); }` },
    { name: "does not infer a custom require loader", filename: "/repo/policy.test.ts", code: `function run(require) { const {readFileSync} = require('fs'); expect(readFileSync('workflow.yml', 'utf8')).toContain('x'); }` },
    { name: "does not call regex extraction an assertion", filename: "/repo/policy.test.ts", code: `${NAMED_FS} const source = readFileSync('workflow.yml', 'utf8'); consume(source.matchAll(/x/g));` },
    { name: "does not trust a locally shadowed expect helper", filename: "/repo/policy.test.ts", code: `${NAMED_FS} const expect = makeVerifier(); const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('x');` },
    { name: "does not trust an expect helper from an unsupported module", filename: "/repo/policy.test.ts", code: `${NAMED_FS} import { expect } from './verification'; const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('x');` },
    { name: "does not trust a non-assert Node export aliased as an assertion", filename: "/repo/policy.test.ts", code: `${NAMED_FS} import { CallTracker as verify } from 'node:assert'; const source = readFileSync('workflow.yml', 'utf8'); verify(source);` },
    { name: "does not trust a locally shadowed assert helper", filename: "/repo/policy.test.ts", code: `${NAMED_FS} function run(assert) { const source = readFileSync('workflow.yml', 'utf8'); assert.match(source, /x/); }` },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('parsed', () => { const parsed = JSON.parse(readFileSync('policy.json', 'utf8')); expect(validate(parsed)).toEqual([]); });` },
    { name: "preserves a parsed TOML contract", filename: "/repo/config.test.ts", code: `${NAMED_FS} test('parsed', () => { const config = parseToml(readFileSync('wrangler.toml', 'utf8')); expect(validate(config)).toEqual([]); });` },
    { filename: "/repo/render.test.ts", code: "test('render', () => { expect(render()).toContain('hello'); });" },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('validator', () => { const source = readFileSync('main.tf', 'utf8'); expect(validate(source)).toEqual([]); });` },
    { filename: "/repo/policy.ts", code: `${NAMED_FS} const source = readFileSync('main.tf', 'utf8'); expect(source).toContain('x');` },
    { filename: "/repo/unrelated.test.ts", code: "const source = client.readFile('main.tf'); expect(source).toContain('resource');" },
    { filename: "/repo/shadow.test.ts", code: `${NAMED_FS} test('shadow', () => { const source = readFileSync('main.tf', 'utf8'); return () => { const source = render(); expect(source).toContain('resource'); }; });` },
    { filename: "/repo/shadow-reader.test.ts", code: `${NAMED_FS} test('shadow', (readFileSync) => { const source = readFileSync('main.tf'); expect(source).toContain('resource'); });` },
    { filename: "/repo/shadow-fs.test.ts", code: `${FS_OBJECT} test('shadow', () => { const fs = client; const source = fs.readFileSync('main.tf'); expect(source).toContain('resource'); });` },
    { filename: "/repo/config.test.ts", code: `${NAMED_FS} import { parse } from 'jsonc-parser'; test('parsed', () => { const config = parse(readFileSync('wrangler.jsonc', 'utf8')); expect(validate(config)).toEqual([]); });` },
  ],
  invalid: [
    {
      name: "recognizes an aliased expect imported from vitest",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import { expect as verify } from 'vitest'; const source = readFileSync('workflow.yml', 'utf8'); verify(source).toContain('x');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes an aliased expect imported from Jest globals",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import { expect as verify } from '@jest/globals'; const source = readFileSync('workflow.yml', 'utf8'); verify(source).toContain('x');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes an aliased expect imported from Playwright",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import { expect as verify } from '@playwright/test'; const source = readFileSync('workflow.yml', 'utf8'); verify(source).toContain('x');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes an aliased expect imported from Bun",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import { expect as verify } from 'bun:test'; const source = readFileSync('workflow.yml', 'utf8'); verify(source).toContain('x');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes a default assert import from the legacy specifier",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import verify from 'assert'; const source = readFileSync('workflow.yml', 'utf8'); verify.match(source, /x/);`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes an assert namespace from the legacy strict specifier",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import * as verify from 'assert/strict'; const source = readFileSync('workflow.yml', 'utf8'); verify.match(source, /x/);`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes an aliased named assertion from node assert",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import { match as verify } from 'node:assert'; const source = readFileSync('workflow.yml', 'utf8'); verify(source, /x/);`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "recognizes an aliased node assert namespace",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import * as verify from 'node:assert/strict'; const source = readFileSync('workflow.yml', 'utf8'); verify.match(source, /x/);`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports a direct assertion on raw JSON source",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} test('raw', () => { const source = readFileSync('policy.json', 'utf8'); expect(source).toContain('enabled'); });`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports a direct assertion on raw TOML source",
      filename: "/repo/config.test.ts",
      code: `${NAMED_FS} test('raw', () => { const source = readFileSync('wrangler.toml', 'utf8'); expect(source).toMatch(/compatibility_date/); });`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    { name: "keeps outer raw provenance after an unrelated block shadow", filename: "/repo/policy.test.ts", code: `${NAMED_FS} const source = readFileSync('workflow.yml', 'utf8'); { const source = 'runtime'; } expect(source).toContain('x');`, errors: [{ messageId: "rawSourceOracle" }] },
    { name: "retains direct regex extraction assertions", filename: "/repo/policy.test.ts", code: `${NAMED_FS} const source = readFileSync('workflow.yml', 'utf8'); expect(source.matchAll(/x/g)).toEqual([]);`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toMatch(/permissions/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.mjs", code: `${FS_OBJECT} test('raw', () => { const source = fs.readFileSync(new URL('./workflow.yml', import.meta.url), 'utf8'); assert.match(source, /permissions:/); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('raw', () => { expect(readFileSync('workflow.yml', 'utf8').trim().includes('permissions')).toBe(true); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8').toString().slice(1); assert.ok(source.indexOf('permissions') >= 0); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source.match(/permissions/)).not.toBeNull(); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); assert(!source.includes('public')); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); assert.doesNotMatch(source, /public/); assert.ok(/permissions/.test(source)); });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: "import { readFile } from 'node:fs/promises'; test('raw', async () => { const source = (await readFile('workflow.yml', 'utf8')).trim(); expect(source).toContain('permissions:'); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/policy.test.ts", code: "const { readFileSync: read } = require('fs'); test('raw', () => { assert.match(read('deploy.sh', 'utf8'), /curl/); });", errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/loop.test.ts", code: `${NAMED_FS} test('raw', () => { const files = ['deploy.sh', 'workflow.yml']; for (const file of files) { expect(readFileSync(file, 'utf8')).toMatch(/deploy|permissions/); } });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/closure.test.ts", code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); return () => { expect(source).toContain('permissions'); }; });`, errors: [{ messageId: "rawSourceOracle" }] },
    { filename: "/repo/two.test.ts", code: `${NAMED_FS} test('source', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('x'); }); test('runtime', () => { const source = render(); expect(source).toContain('x'); });`, errors: [{ messageId: "rawSourceOracle" }] },
    {
      filename: "/repo/policy.test.mjs",
      code: `${NAMED_FS} test('raw', () => { const source = readFileSync('workflow.yml', 'utf8'); expect(source).toContain('permissions'); expect(source).toMatch(/permissions/); });`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      filename: "/repo/independent.test.mjs",
      code: `${NAMED_FS} test('raw', () => { const script = readFileSync('deploy.sh', 'utf8'); expect(script).toContain('deploy'); const workflow = readFileSync('workflow.yml', 'utf8'); expect(workflow).toContain('permissions:'); });`,
      errors: [{ messageId: "rawSourceOracle" }, { messageId: "rawSourceOracle" }],
    },
    {
      name: "reports a direct raw JSONC assertion",
      filename: "/repo/config.test.ts",
      code: `${NAMED_FS} test('raw', () => { const source = readFileSync('wrangler.jsonc', 'utf8'); expect(source).toMatch(/NEXT_PUBLIC_ENVIRONMENT/); });`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
  ],
});
