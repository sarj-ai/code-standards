import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/no-frontend-comments.js";
import noTestComments from "../../src/rules/no-test-comments.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({ languageOptions: { parser } });

const EMPTY_COMMENT_FIXTURES = [
  { name: "return token separation", code: "export function identity(value: number) { return/**/value; }", output: "export function identity(value: number) { return value; }" },
  { name: "operator token separation", code: "export const result = left+/**/+right;", output: "export const result = left+ +right;" },
  { name: "async token separation", code: "export async/**/function selected() {}", output: "export async function selected() {}" },
  { name: "directive prologue", code: "'use client';/**/export const ready = true;", output: "'use client'; export const ready = true;" },
  { name: "line feed", code: "//\nexport const ready = true;", output: " \nexport const ready = true;" },
  { name: "CRLF", code: "// \r\nexport const ready = true;", output: " \r\nexport const ready = true;" },
  { name: "line separator", code: "//\u2028export const ready = true;", output: " \u2028export const ready = true;" },
  { name: "paragraph separator", code: "//\u2029export const ready = true;", output: " \u2029export const ready = true;" },
  { name: "BOM", code: "\ufeff//\nexport const ready = true;", output: "\ufeff \nexport const ready = true;" },
  { name: "EOF", code: "export const ready = true;/* */", output: "export const ready = true; " },
  { name: "before JSX", code: "//\nexport const View = () => <p />;", output: " \nexport const View = () => <p />;" },
  { name: "between JSX roots", code: "export const First = <p />;/**/export const Second = <><span /></>;", output: "export const First = <p />; export const Second = <><span /></>;" },
  { name: "after nested JSX", code: "export const View = <p><span /></p>;/* */", output: "export const View = <p><span /></p>; " },
] as const;

const MANUAL_EMPTY_COMMENT_FIXTURES = [
  { name: "multiline LF", code: "export function selected(value: number) { return/*\n*/value; }" },
  { name: "multiline CRLF", code: "export function selected(value: number) { return/*\r\n*/value; }" },
  { name: "multiline line separator", code: "export function selected(value: number) { return/*\u2028*/value; }" },
  { name: "multiline paragraph separator", code: "export function selected(value: number) { return/*\u2029*/value; }" },
  { name: "JSX empty expression", code: "export const View = () => <p>{/**/}Ready</p>;" },
  { name: "JSX expression ancestry", code: "export const View = () => <p>{left+/**/+right}</p>;" },
  { name: "JSX fragment", code: "export const View = () => <>{/**/}</>;" },
] as const;

TESTER.run("no-frontend-comments", rule, {
  valid: [
    { filename: "src/view.test.tsx", code: "//\nconst ready = true;" },
    { filename: "src/generated/view.tsx", code: "//\nexport const ready = true;" },
    { filename: "src/view.tsx", code: "export const View = () => <p>Ready</p>;" },
    { filename: "src/view.tsx", code: "const text = '// literal text'; const template = '/* literal */';" },
    { filename: "src/view.tsx", code: "const View = () => <p>// rendered text</p>;" },
    { filename: "src/generated/view.tsx", code: "// Generated upstream\nexport const View = () => null;" },
    { filename: "src/worker.ts", code: "// Server library context\nexport const ready = true;" },
    { filename: "src/view.test.tsx", code: "// Owned by the test-comment rule\nconst ready = true;" },
  ],
  invalid: [
    ...EMPTY_COMMENT_FIXTURES.map(({ name, code, output }) => ({ name, filename: "src/helper.tsx", code, output, errors: [{ messageId: "noFrontendComments" as const }] })),
    ...MANUAL_EMPTY_COMMENT_FIXTURES.map(({ name, code }) => ({ name, filename: "src/view.tsx", code, output: null, errors: [{ messageId: "noFrontendComments" as const }] })),
    { filename: "src/view.tsx", code: "// Render the view\nexport const View = () => <p />;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "export const View = () => <p>{/* View status */}Ready</p>;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "/** Public view documentation */\nexport const View = () => null;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/use-view.ts", code: "import { useState } from 'react';\n// Browser helper\nexport const useView = () => useState(true);", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/actions.ts", code: "'use server';\n// Save the changes\nexport async function save() {}", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/client.ts", code: "'use client';\n// Client module\nexport const ready = true;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/helper.ts", code: "// Frontend helper\nexport const ready = true;", options: [{ allFiles: true }], output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "// @ts-expect-error -- invalid fixture\nconst ready: number = 'bad';", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "/* Copyright 2026 Example */\nexport const ready = true;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { filename: "src/view.tsx", code: "/*#__PURE__*/ makeView();", output: null, errors: [{ messageId: "noFrontendComments" }] },
  ],
});

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

it("delegates frontend test comments once and preserves behavioral annotations during fixing", () => {
  const code = "// @ts-expect-error -- invalid fixture\nconst ready: number = 'bad';";
  const linter = new Linter();
  const configuration = [{
    files: ["**/*.tsx"],
    languageOptions: { parser },
    plugins: { sarj: { rules: { "no-frontend-comments": rule, "no-test-comments": noTestComments } } },
    rules: { "sarj/no-frontend-comments": "warn", "sarj/no-test-comments": "warn" },
  }] as const;
  const result = linter.verifyAndFix(code, configuration, { filename: "src/view.test.tsx" });
  expect(result.output).toBe(code);
  expect(result.messages.map(message => message.ruleId)).toEqual(["sarj/no-test-comments"]);
});

it.each(EMPTY_COMMENT_FIXTURES)("preserves native tokens and line endings for $name and converges", ({ code, output }) => {
  const linter = new Linter();
  const configuration = [{
    files: ["**/*.tsx"],
    languageOptions: { parser },
    plugins: { sarj: { rules: { "no-frontend-comments": rule } } },
    rules: { "sarj/no-frontend-comments": "warn" },
  }] as const;
  const filename = "src/helper.tsx";
  const first = linter.verifyAndFix(code, configuration, { filename });
  expect(first.output).toBe(output);
  expect(first.messages).toEqual([]);
  expect(nativeTokens(first.output)).toEqual(nativeTokens(code));
  expect(first.output.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [])
    .toEqual(code.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? []);
  const second = linter.verifyAndFix(first.output, configuration, { filename });
  expect(second.fixed).toBe(false);
  expect(second.output).toBe(first.output);
  expect(second.messages).toEqual([]);
});

it("fixes empty comments outside JSX while retaining inner comments and converging", () => {
  const code = "//\r\nexport const View = <><p>{/**/}Ready</p></>;/**/";
  const output = " \r\nexport const View = <><p>{/**/}Ready</p></>; ";
  const linter = new Linter();
  const configuration = [{
    files: ["**/*.tsx"],
    languageOptions: { parser },
    plugins: { sarj: { rules: { "no-frontend-comments": rule } } },
    rules: { "sarj/no-frontend-comments": "warn" },
  }] as const;
  const filename = "src/helper.tsx";
  const first = linter.verifyAndFix(code, configuration, { filename });
  expect(first.output).toBe(output);
  expect(first.messages.map(message => message.messageId)).toEqual(["noFrontendComments"]);
  expect(first.messages[0]?.fix).toBeUndefined();
  expect(nativeTokens(first.output)).toEqual(nativeTokens(code));
  expect(first.output.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? [])
    .toEqual(code.match(/\r\n|[\r\n\u2028\u2029]/gu) ?? []);
  const second = linter.verifyAndFix(first.output, configuration, { filename });
  expect(second.fixed).toBe(false);
  expect(second.output).toBe(output);
  expect(second.messages).toEqual(first.messages);
});

function nativeTokens(source: string): readonly string[] {
  const tokens = parser.parseForESLint(source, {
    filePath: "src/helper.tsx", sourceType: "module", ecmaFeatures: { jsx: true }, tokens: true, range: true, loc: true,
  }).ast.tokens;
  if (tokens === undefined) throw new Error("Native parsing did not return the required token stream.");
  return tokens.map(token => `${token.type}:${token.value}`);
}
