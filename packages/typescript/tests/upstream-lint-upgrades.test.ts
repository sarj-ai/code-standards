import { ESLint, type Linter } from "eslint";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { createConfig } from "../../standards/src/sarj_standards/configs/eslint.strict.mjs";

const CASES = [
  ["no-conflicting-constraints", "<input type='number' min={10} max={5} />;", "<input type='number' min={5} max={10} />;"],
  ["no-incomplete-accessor-override", "class Base { get value() { return 1; } set value(input) {} } class Child extends Base { get value() { return 2; } }", "class Base { get value() { return 1; } } class Child extends Base { get value() { return 2; } }"],
  ["no-ineffective-csp-directives", "<meta httpEquiv='Content-Security-Policy' content=\"frame-ancestors 'none'\" />;", "<meta httpEquiv='Content-Security-Policy' content=\"default-src 'self'\" />;"],
  ["no-invalid-boolean-attribute-value", "const button = document.createElement('button'); button.setAttribute('disabled', 'false');", "const button = document.createElement('button'); button.setAttribute('disabled', '');"],
  ["no-invalid-dom-token", "element.classList.add('primary active');", "element.classList.add('primary', 'active');"],
  ["no-invalid-integrity", "<script src='app.js' integrity='sha256-abc' />;", "<script src='app.js' integrity='sha256-LPJNul+wow4m6DsqxbninhsWHlwfp0JecwQzYpOLmCQ=' />;"],
  ["no-invalid-intl-options", "new Intl.NumberFormat('en', { style: 'currency' });", "new Intl.NumberFormat('en', { style: 'currency', currency: 'USD' });"],
  ["no-invalid-property-descriptor", "Object.defineProperty(object, 'value', { get: getter, writable: false });", "Object.defineProperty(object, 'value', { get: getter });"],
  ["no-invalid-response-options", "new Response('body', { status: 204 });", "new Response(null, { status: 204 });"],
  ["no-invalid-style-set-property", "element.style.setProperty('backgroundColor', 'red');", "element.style.setProperty('background-color', 'red');"],
  ["no-invalid-temporal-arithmetic", "Temporal.Now.instant().add({ days: 1 });", "Temporal.Now.instant().add({ hours: 24 });"],
  ["no-invalid-url-protocol-comparison", "new URL(input).protocol === 'https';", "new URL(input).protocol === 'https:';"],
  ["no-leading-empty-lines", "\nconst value = 1;", "const value = 1;"],
  ["no-prevent-default-in-passive-listener", "element.addEventListener('wheel', event => event.preventDefault(), { passive: true });", "element.addEventListener('wheel', event => event.preventDefault(), { passive: false });"],
  ["no-unnecessary-default-arguments", "function run(enabled = true) { return enabled; } run(true);", "function run(enabled = true) { return enabled; } run(false);"],
  ["no-unnecessary-parameters", "function run(value, unit) { return value + unit; } run(1, 'px'); run(2, 'px');", "export function run(value, unit) { return value + unit; } run(1, 'px'); run(2, 'px');"],
  ["no-unsafe-json-serialization", "JSON.stringify({ value: 1n });", "JSON.stringify({ value: '1' });"],
  ["no-url-in-search-params", "new URLSearchParams('https://example.com/?value=1');", "new URLSearchParams('value=1');"],
  ["prefer-escaped-irregular-whitespace", "const value = '\u00a0';", "const value = '\\u{A0}';"],
  ["prefer-literal-ascii", "const value = '\\x41';", "const value = 'A';"],
  ["prefer-short-escape-sequences", "const value = '\\u000A';", "const value = '\\n';"],
  ["require-text-decoder-streaming", "const response = await fetch(url); const decoder = new TextDecoder(); for await (const chunk of response.body) { decoder.decode(chunk); }", "const response = await fetch(url); const decoder = new TextDecoder(); for await (const chunk of response.body) { decoder.decode(chunk, { stream: true }); } decoder.decode();"],
] as const;

function focusedConfig(ruleId: string, options = { projectService: false, tsconfigRootDir: process.cwd() }): Linter.Config[] {
  const factory = createConfig as unknown as (options: { projectService: boolean; tsconfigRootDir: string }) => Linter.Config[];
  return factory(options).map(entry => ({
    ...entry,
    rules: Object.fromEntries(Object.entries(entry.rules ?? {}).filter(([id]) => id === ruleId)),
  }));
}

describe("new upstream checks execute through the managed preset", () => {
  it.each(CASES)("%s rejects its defect and accepts the correction", async (name, invalid, valid) => {
    const ruleId = `unicorn/${name}`;
    const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: focusedConfig(ruleId) });
    const [bad] = await eslint.lintText(invalid, { filePath: "src/upgrade-probe.tsx" });
    expect(bad?.messages.length).toBeGreaterThan(0);
    expect(bad?.messages.every(message => message.ruleId === ruleId && message.severity === 2)).toBe(true);
    const [good] = await eslint.lintText(valid, { filePath: "src/upgrade-probe.tsx" });
    expect(good?.messages).toEqual([]);
  });

  it("keeps repeated conversion advice non-blocking and preserves escaped functions", async () => {
    const ruleId = "unicorn/no-repeated-call-wrappers";
    const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: focusedConfig(ruleId) });
    const [bad] = await eslint.lintText("const words = text => text.split(' '); new Set(words(first)); new Set(words(second));", { filePath: "src/upgrade-probe.ts" });
    expect(bad?.messages.map(message => [message.ruleId, message.severity])).toEqual([[ruleId, 1]]);
    const [good] = await eslint.lintText("const words = text => text.split(' '); new Set(words(first)); words(second);", { filePath: "src/upgrade-probe.ts" });
    expect(good?.messages).toEqual([]);
  });

  it("preserves distinct promise wrappers when applying managed fixes", async () => {
    const ruleId = "unicorn/prefer-promise-static-methods";
    const source = "const seed = Promise.resolve(1); const wrapped = new Promise(resolve => resolve(seed));";
    const eslint = new ESLint({ overrideConfigFile: true, overrideConfig: focusedConfig(ruleId), fix: true });
    const [result] = await eslint.lintText(source, { filePath: "src/upgrade-probe.ts" });
    expect(result?.messages).toEqual([]);
    expect(result?.output).toBeUndefined();
  });

  it("rejects numeric enum assignments and accepts named enum members", async () => {
    const ruleId = "@typescript-eslint/no-unsafe-enum-assignment";
    const root = fileURLToPath(new URL("./fixtures/runs/", import.meta.url));
    const eslint = new ESLint({ cwd: root, overrideConfigFile: true, overrideConfig: focusedConfig(ruleId, { projectService: true, tsconfigRootDir: root }) });
    const [bad] = await eslint.lintText("enum Kind { Active } const kind: Kind = 0;", { filePath: "example.ts" });
    expect(bad?.messages.map(message => [message.ruleId, message.severity])).toEqual([[ruleId, 2]]);
    const [good] = await eslint.lintText("enum Kind { Active } const kind: Kind = Kind.Active;", { filePath: "example.ts" });
    expect(good?.messages).toEqual([]);
  });
});
