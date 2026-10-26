// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { ESLint } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import iacRule from "../../src/rules/iac-source-coupled-test.js";
import rule from "../../src/rules/source-coupled-test.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { sourceType: "module" } } });
const NAMED_FS = "import { readFileSync } from 'node:fs';";
const FS_OBJECT = "import fs from 'node:fs';";

it.each([
  ["policy.json", "source-coupled-test"],
  ["main.tf.jsonc", "source-coupled-test"],
  ["main.tf.json", "iac-source-coupled-test"],
  ["main.tftest.json", "iac-source-coupled-test"],
])("assigns %s to its single source-oracle owner", async (path, owner) => {
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: [{
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { sarj: { rules: { "source-coupled-test": rule, "iac-source-coupled-test": iacRule } } },
      rules: { "sarj/source-coupled-test": "error", "sarj/iac-source-coupled-test": "error" },
    }],
  });
  const [result] = await eslint.lintText(
    `${NAMED_FS} test('policy', () => { expect(readFileSync('${path}', 'utf8')).toContain('resource'); });`,
    { filePath: "policy.test.ts" },
  );
  expect(result?.messages.map(message => [message.ruleId, message.line])).toEqual([[`sarj/${owner}`, 1]]);
});

TESTER.run("source-coupled-test", rule, {
  valid: [
    { name: "allows relative cancellation that stays inside the proven temporary directory", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync(prefix); const pages = resolve(output, 'pages', '..', 'result'); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');" },
    { name: "preserves the existing direct temporary alias depth boundary", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const d0 = mkdtempSync(prefix); const d1 = d0; const d2 = d1; const d3 = d2; const d4 = d3; const d5 = d4; const d6 = d5; const d7 = d6; expect(readFileSync(join(d7, 'index.html'), 'utf8')).toContain('<main>');" },
    { name: "preserves generated HTML in a stable native temporary descendant", filename: "/repo/generated.test.ts", code: "import { mkdtemp, readFile, writeFile } from 'node:fs/promises'; import { tmpdir } from 'node:os'; import { join } from 'node:path'; test('generated output', async () => { const output = await mkdtemp(join(tmpdir(), 'private-build-')); const pages = join(output, 'pages', 'api'); await writeFile(join(pages, 'index.html'), '<main>Ready</main>'); await finalizeBuild({ clientRoot: output }); const html = await readFile(join(pages, 'index.html'), 'utf8'); expect(html).toContain('<main>'); });" },
    { name: "preserves the awaited generated-output identity contract", filename: "/repo/generated.test.ts", code: "import { mkdtemp, readFile } from 'node:fs/promises'; import { join } from 'node:path'; test('generated shell', async () => { const output = await mkdtemp(prefix); const pages = join(output, 'pages'); const shell = '<main>Ready</main>'; await build(output); await expect(readFile(join(pages, 'index.html'), 'utf8')).resolves.toBe(shell); });" },
    { name: "follows immutable aliases of a contained temporary descendant", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = mkdtempSync(prefix); const pages = join(output, 'pages'); const stable = pages; const file = join(stable, 'index.html'); expect(readFileSync(file, 'utf8')).toContain('<main>');" },
    { name: "follows genuine aliased native makers and contained path resolvers", filename: "/repo/generated.test.ts", code: "import { mkdtempSync as makeTemp, readFileSync } from 'node:fs'; import { resolve as resolvePath } from 'node:path'; const output = makeTemp(prefix); const pages = resolvePath(output, 'pages'); expect(readFileSync(resolvePath(pages, 'index.html'), 'utf8')).toContain('<main>');" },
    { name: "preserves nested inline builders that remain contained", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = mkdtempSync(prefix); expect(readFileSync(join(join(output, 'pages', '.'), 'index.html'), 'utf8')).toContain('<main>');" },
    { name: "preserves literal mutation nonidentity guards before compiler checks", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; import assert from 'node:assert/strict'; const source = readFileSync(join(ROOT, 'view.tsx'), 'utf8'); const mutated = source.replaceAll('<Icon', '<MissingIcon'); assert.notEqual(mutated, source); expect(compile(mutated)).toHaveLength(1);` },
    { name: "preserves the matcher form of a literal mutation guard", filename: "/repo/view.test.tsx", code: `${NAMED_FS} const source = readFileSync('view.tsx', 'utf8'); expect(source.replace(/Icon/g, 'MissingIcon')).not.toBe(source);` },
    { name: "preserves generated data beneath a native temporary directory", filename: "/repo/policy.test.ts", code: `import { readFileSync, mkdtempSync, writeFileSync } from 'node:fs'; import { join } from 'node:path'; const directory = mkdtempSync(prefix); writeFileSync(join(directory, 'policy.json'), '{}'); expect(readFileSync(join(directory, 'policy.json'), 'utf8')).toBe('{}');` },
    { name: "preserves component parser contracts", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; const ast = parse(readFileSync(join(ROOT, 'view.tsx'), 'utf8')); expect(ast.children).toHaveLength(1);` },
    { name: "preserves component representation fixtures", filename: "/repo/parser.test.ts", code: `${NAMED_FS} import { join } from 'node:path'; expect(readFileSync(join(ROOT, 'fixtures/view.tsx'), 'utf8')).toContain('<View />');` },
    { name: "preserves a joined representation directory", filename: "/repo/parser.test.ts", code: `${NAMED_FS} import { join } from 'node:path'; expect(readFileSync(join(ROOT, 'golden', 'view.html'), 'utf8')).toContain('<View />');` },
    { name: "preserves rendered HTML assertions", filename: "/repo/view.test.ts", code: "const html = renderView(); expect(html).toContain('aria-label=');" },
    { name: "preserves generated component source", filename: "/repo/view.test.ts", code: `${NAMED_FS} expect(readFileSync('generated/view.tsx', 'utf8')).toContain('<View />');` },
    { name: "does not infer a locally shadowed path join", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; function run(join) { expect(readFileSync(join(ROOT, 'view.tsx'), 'utf8')).toContain('useEffect('); }` },
    { name: "does not infer a custom path join", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from './paths'; expect(readFileSync(join(ROOT, 'view.tsx'), 'utf8')).toContain('useEffect(');` },
    { name: "does not infer a reassigned path alias", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; let path = join(ROOT, 'view.tsx'); path = renderedPath; expect(readFileSync(path, 'utf8')).toContain('useEffect(');` },
    { name: "preserves an absolute resolved fixture path", filename: "/repo/parser.test.ts", code: `${NAMED_FS} import { resolve } from 'node:path'; expect(readFileSync(resolve(ROOT, 'src', '/fixtures/view.tsx'), 'utf8')).toContain('<View />');` },
    { name: "does not infer a shadowed filesystem reader through a path join", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; function run(readFileSync) { expect(readFileSync(join(ROOT, 'view.tsx'), 'utf8')).toContain('useEffect('); }` },
    { name: "requires the final path component to prove a source suffix", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; expect(readFileSync(join(ROOT, 'view.tsx', name), 'utf8')).toContain('useEffect(');` },
    { name: "does not match a non-source final path component", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; expect(readFileSync(join(ROOT, 'view.tsx', '.log'), 'utf8')).toContain('useEffect(');` },
    { name: "does not infer spread path segments", filename: "/repo/view.test.tsx", code: `${NAMED_FS} import { join } from 'node:path'; expect(readFileSync(join(ROOT, 'view.tsx', ...segments), 'utf8')).toContain('useEffect(');` },
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
    { name: "rejects a nested absolute resolve that spells the former proof sentinel", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); const pages = resolve(output, '/__source_oracle_temporary_directory__/src'); expect(readFileSync(join(pages, 'index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "rejects nested traversal out of the actual root and reentry by the former sentinel name", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); const pages = join(output, '..', '__source_oracle_temporary_directory__', 'src'); expect(readFileSync(join(pages, 'index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "rejects the inherited direct absolute resolve sentinel collision", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); expect(readFileSync(resolve(output, '/__source_oracle_temporary_directory__/src/index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "rejects the inherited direct traversal and sentinel-name reentry", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); expect(readFileSync(join(output, '..', '__source_oracle_temporary_directory__', 'src', 'index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "rejects a native drive-absolute resolve reset", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); const pages = resolve(output, 'C:\\\\__source_oracle_temporary_directory__\\\\src'); expect(readFileSync(join(pages, 'index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "rejects a drive-anchored resolve whose directory cannot be proven", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); const pages = resolve(output, 'C:__source_oracle_temporary_directory__/src'); expect(readFileSync(join(pages, 'index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "normalizes backslashes before rejecting an absolute resolve reset", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync('/tmp/private-'); const pages = resolve(output, '\\\\__source_oracle_temporary_directory__\\\\src'); expect(readFileSync(join(pages, 'index.ts'), 'utf8')).toContain('source');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not infer a temporary origin from a cyclic path initializer", filename: "/repo/generated.test.ts", code: "import { readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = join(output, 'pages'); expect(readFileSync(join(output, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not infer a custom temporary maker in a nested path", filename: "/repo/generated.test.ts", code: "import { readFileSync } from 'node:fs'; import { mkdtempSync } from './temporary'; import { join } from 'node:path'; const output = mkdtempSync(prefix); const pages = join(output, 'pages'); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not infer a shadowed native temporary maker in a nested path", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; function verify(mkdtempSync) { const output = mkdtempSync(prefix); const pages = join(output, 'pages'); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>'); }", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not exempt a reassigned temporary root", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; let output = mkdtempSync(prefix); output = ROOT; const pages = join(output, 'pages'); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not exempt a reassigned contained alias", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = mkdtempSync(prefix); let pages = join(output, 'pages'); pages = ROOT; expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not exempt a nested path escaping its proven directory", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = mkdtempSync(prefix); const pages = join(output, 'pages'); expect(readFileSync(join(pages, '..', '..', 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not treat an escaped intermediate directory as temporary", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = mkdtempSync(prefix); const pages = join(output, '..', 'src'); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not exempt an absolute intermediate resolver reset", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join, resolve } from 'node:path'; const output = mkdtempSync(prefix); const pages = resolve(output, '/repository/pages'); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    { name: "does not infer containment through dynamic intermediate segments", filename: "/repo/generated.test.ts", code: "import { mkdtempSync, readFileSync } from 'node:fs'; import { join } from 'node:path'; const output = mkdtempSync(prefix); const pages = join(output, selectedDirectory); expect(readFileSync(join(pages, 'index.html'), 'utf8')).toContain('<main>');", errors: [{ messageId: "rawSourceOracle" }] },
    {
      name: "does not exempt comparisons to fixed source spelling as mutation guards",
      filename: "/repo/view.test.tsx",
      code: `${NAMED_FS} const source = readFileSync('view.tsx', 'utf8'); expect(source.replaceAll('Icon', 'MissingIcon')).not.toBe('');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "does not exempt paths escaping a fresh directory",
      filename: "/repo/policy.test.ts",
      code: `import { readFileSync, mkdtempSync } from 'node:fs'; import { join } from 'node:path'; const directory = mkdtempSync(prefix); expect(readFileSync(join(directory, '..', 'policy.json'), 'utf8')).toContain('permissions');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "resets prior directories at an absolute resolved path",
      filename: "/repo/view.test.tsx",
      code: `${NAMED_FS} import { resolve } from 'node:path'; expect(readFileSync(resolve(ROOT, 'fixtures', '/src/view.tsx'), 'utf8')).toContain('useEffect(');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports literal CSS declarations instead of computed layout",
      filename: "/repo/view.test.mjs",
      code: `${NAMED_FS} const css = readFileSync(new URL('../public/chat.css', import.meta.url), 'utf8'); assert.match(css, /padding:9px 11px/);`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports source HTML string order instead of rendered behavior",
      filename: "/repo/view.test.mjs",
      code: `${NAMED_FS} const html = readFileSync(new URL('../public/index.html', import.meta.url), 'utf8'); assert.ok(html.indexOf('style.css') < html.indexOf('chat.css'));`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "normalizes source paths that leave a representation directory",
      filename: "/repo/view.test.tsx",
      code: `${NAMED_FS} import { join } from 'node:path'; expect(readFileSync(join(ROOT, 'fixtures', '../view.tsx'), 'utf8')).toContain('useEffect(');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports component source spelling through a proven path join and source slice",
      filename: "/repo/view.test.tsx",
      code: `${NAMED_FS} import { join } from 'node:path'; const source = readFileSync(join(ROOT, 'context/view.tsx'), 'utf8'); const consumer = source.slice(source.indexOf('export function useView')); expect(consumer).toContain('useEffect(() => watch(), [watch]);');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports JSX source through an aliased native path resolver",
      filename: "/repo/view.test.ts",
      code: `${NAMED_FS} import { resolve as resolvePath } from 'path'; const source = readFileSync(resolvePath(ROOT, 'view.jsx'), 'utf8'); expect(source).not.toContain('legacyView');`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
    {
      name: "reports a stable joined read alias while deduplicating its assertions",
      filename: "/repo/policy.test.ts",
      code: `${NAMED_FS} import { join } from 'node:path'; const path = join(ROOT, 'workflow.yml'); const source = readFileSync(path, 'utf8'); expect(source).toContain('permissions'); expect(source).toMatch(/contents/);`,
      errors: [{ messageId: "rawSourceOracle" }],
    },
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
