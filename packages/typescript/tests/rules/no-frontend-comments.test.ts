import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterAll } from "vitest";

import rule from "../../src/rules/no-frontend-comments.js";
import noTestComments from "../../src/rules/no-test-comments.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

const TEMP = mkdtempSync(join(tmpdir(), "frontend-ownership-"));
afterAll(() => rmSync(TEMP, { recursive: true, force: true }));

function manifest(frontend: boolean): string {
  return JSON.stringify(frontend ? { private: true, dependencies: { react: "19.2.0" } } : { private: true });
}

function packageDirectory(name: string): string {
  const directory = join(TEMP, name);
  mkdirSync(directory, { recursive: true });
  return directory;
}

const PACKAGE_DIRECTORY = packageDirectory("package");
const PACKAGE_SCENARIO = {
  helper: join(PACKAGE_DIRECTORY, "src", "helper.ts"),
  frontend: () => writeFileSync(join(PACKAGE_DIRECTORY, "package.json"), manifest(true)),
};

const OWNERSHIP_CODE = "// The current package owns this helper\nexport const ownership = 1;";
const OWNERSHIP_CASES = [
  { name: "removed dependency with source text", initial: true, current: false },
  { name: "added dependency with source text", initial: false, current: true },
  { name: "removed dependency with an existing source object", initial: true, current: false },
  { name: "added dependency with an existing source object", initial: false, current: true },
].flatMap(({ name, initial, current }, index) => {
  const directory = packageDirectory(`ownership-${index}`);
  const filename = join(directory, "helper.ts");
  return [["initial", initial], ["current", current]].map(([phase, frontend]) => ({
    name: `refreshes package ownership for ${name} (${phase})`,
    filename,
    frontend: frontend === true,
    before: () => writeFileSync(join(directory, "package.json"), manifest(frontend === true)),
  }));
});

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
    { name: "example named-view", filename: "src/view.tsx", code: "export const View = () => <p>Ready</p>;\n" },
    { name: "example package-helper-code", filename: PACKAGE_SCENARIO.helper, code: "export const ready = true;", before: PACKAGE_SCENARIO.frontend },
    { name: "example empty-comment-removed", filename: "src/example/helper.tsx", code: "export function identity(value: number) { return value; }" },
    ...EMPTY_COMMENT_FIXTURES.map(({ name, output }) => ({ name: `${name} converges`, filename: "src/helper.tsx", code: output })),
    { name: "delegates frontend test comments once", filename: "src/view.test.tsx", code: "// @ts-expect-error -- invalid fixture\nconst ready: number = 'bad';" },
    ...OWNERSHIP_CASES.filter(testCase => !testCase.frontend).map(({ name, filename, before }) => ({ name, filename, code: OWNERSHIP_CODE, before })),
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
    { name: "example frontend-prose", filename: "src/view.tsx", code: "// Show current status\nexport const View = () => <p>Ready</p>;", output: null, errors: [{ messageId: "noFrontendComments" }] },
    { name: "example package-helper", filename: PACKAGE_SCENARIO.helper, code: "// Frontend helper\nexport const ready = true;", before: PACKAGE_SCENARIO.frontend, output: null, errors: [{ messageId: "noFrontendComments" }] },
    { name: "example empty-comment-separator", filename: "src/example/helper.tsx", code: "export function identity(value: number) { return/**/value; }", output: "export function identity(value: number) { return value; }", errors: [{ messageId: "noFrontendComments" }] },
    { name: "fixes empty comments outside JSX while retaining inner comments", filename: "src/helper.tsx", code: "//\r\nexport const View = <><p>{/**/}Ready</p></>;/**/", output: " \r\nexport const View = <><p>{/**/}Ready</p></>; ", errors: [{ messageId: "noFrontendComments" }, { messageId: "noFrontendComments" }, { messageId: "noFrontendComments" }] },
    { name: "retains the inner JSX comment after fixing", filename: "src/helper.tsx", code: " \r\nexport const View = <><p>{/**/}Ready</p></>; ", output: null, errors: [{ messageId: "noFrontendComments" }] },
    ...OWNERSHIP_CASES.filter(testCase => testCase.frontend).map(({ name, filename, before }) => ({ name, filename, code: OWNERSHIP_CODE, before, output: null, errors: [{ messageId: "noFrontendComments" as const }] })),
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

TESTER.run("no-test-comments", noTestComments, {
  valid: [],
  invalid: [
    { name: "delegates frontend test comments once", filename: "src/view.test.tsx", code: "// @ts-expect-error -- invalid fixture\nconst ready: number = 'bad';", output: null, errors: [{ messageId: "testComment" }] },
  ],
});
