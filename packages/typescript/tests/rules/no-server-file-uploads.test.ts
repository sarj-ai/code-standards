// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_SERVER_FILE_UPLOADS_DOCUMENTATION } from "../../src/rules/no-server-file-uploads.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-server-file-uploads", rule, {
  valid: [
    { name: "browser signed upload", code: NO_SERVER_FILE_UPLOADS_DOCUMENTATION.examples[0].files[0].source },
    { name: "server object metadata", code: NO_SERVER_FILE_UPLOADS_DOCUMENTATION.examples[3].files[0].source },
    { name: "ordinary browser script", code: "const file = new File(['data'], 'data.txt'); await fetch(signedUrl, { method: 'PUT', body: file });" },
    { name: "filename does not prove server intent", filename: "/app/api/upload/route.ts", code: "export function selected(file: File) { return file.name; }" },
    { name: "client with type-only server import", code: "'use client'; import type { NextRequest } from 'next/server'; export type Selected = File;" },
    { name: "type import alone is not a server boundary", code: "import type { NextRequest } from 'next/server'; export type Selected = File;" },
    { name: "inline erased server specifier", code: "import { type NextRequest } from 'next/server'; export type Selected = File;" },
    { name: "Hono browser client", code: "import { hc } from 'hono/client'; export async function upload(file: File) { await fetch(signedUrl, { method: 'PUT', body: file }); }" },
    { name: "string-only form", code: "'use server'; export async function save(form: FormData) { return form.get('title'); }" },
    { name: "server-generated binary download", code: "'use server'; export function download() { return new Blob(['report']); }" },
    { name: "local File class", code: "'use server'; class File {} const file = new File();" },
    { name: "shadowed File parameter", code: "'use server'; function check(File: Function) { return input instanceof File; }" },
    { name: "unrelated imported File", code: "'use server'; import { File } from './domain'; export type Input = File;" },
    { name: "local type File", code: "'use server'; interface File { objectKey: string } export function save(file: File) { return file.objectKey; }" },
    { name: "unrelated member", code: "'use server'; const value = schema.File;" },
    { name: "shadowed global namespace", code: "'use server'; function local(globalThis: { File: unknown }) { return globalThis.File; }" },
    { name: "computed unrelated member", code: "'use server'; import * as buffer from './domain'; const value = buffer['File'];" },
    { name: "comments and strings", code: "'use server'; // File\nconst label = 'File';" },
    { name: "later string is not a directive", code: "run(); 'use server'; const file = new File([], 'item');" },
    { name: "nested client code outside server function", code: "async function action() { 'use server'; return objectKey; } function preview(file: File) { return file.name; }" },
    { name: "unrelated namespace type", code: "'use server'; import * as domain from './domain'; export type Value = domain.File;" },
    { name: "type query member name is not a reference", code: "'use server'; export type Input = { File: string };" },
    { name: "destructuring an unrelated File", code: "'use server'; const { File } = domain; const value = new File();" },
    { name: "browser File destructuring", code: "'use client'; const { File: NativeFile } = globalThis; const value = new NativeFile([], 'item');" },
    { name: "browser buffer File", code: "'use client'; import { File as NativeFile } from 'node:buffer'; const value = new NativeFile([], 'item');" },
  ],
  invalid: [
    { name: "server File parameter", code: NO_SERVER_FILE_UPLOADS_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "serverFile" }] },
    { name: "Hono file upload", code: NO_SERVER_FILE_UPLOADS_DOCUMENTATION.examples[2].files[0].source, errors: [{ messageId: "serverFile" }] },
    { name: "server-only runtime validation", code: "import 'server-only'; const valid = input instanceof File;", errors: [{ messageId: "serverFile" }] },
    { name: "Next.js server route", code: "import { NextResponse } from 'next/server'; export async function POST(request: Request) { const data = await request.formData(); return NextResponse.json({ valid: data.get('file') instanceof File }); }", errors: [{ messageId: "serverFile" }] },
    { name: "Next.js namespace import", code: "import * as server from 'next/server'; const valid = input instanceof File;", errors: [{ messageId: "serverFile" }] },
    { name: "OpenAPI Hono route", code: "import { OpenAPIHono } from '@hono/zod-openapi'; const app = new OpenAPIHono(); const valid = input instanceof File;", errors: [{ messageId: "serverFile" }] },
    { name: "server constructor", code: "'use server'; const file = new File([], 'item');", errors: [{ messageId: "serverFile" }] },
    { name: "server constructor capture", code: "'use server'; const NativeFile = File; const valid = input instanceof NativeFile;", errors: [{ messageId: "serverFile" }] },
    { name: "inline server action parameter", code: "export async function save(file: File) { 'use server'; return file.name; }", errors: [{ messageId: "serverFile" }] },
    { name: "inline server function expression", code: "export const save = async function(file: File) { 'use server'; return file.name; };", errors: [{ messageId: "serverFile" }] },
    { name: "inline server arrow", code: "export const save = async (file: File) => { 'use server'; return file.name; };", errors: [{ messageId: "serverFile" }] },
    { name: "server type alias", code: "'use server'; export type Input = File[];", errors: [{ messageId: "serverFile" }] },
    { name: "server assertion", code: "'use server'; const input = value as File;", errors: [{ messageId: "serverFile" }] },
    { name: "global namespace", code: "'use server'; const valid = input instanceof globalThis.File;", errors: [{ messageId: "serverFile" }] },
    { name: "computed global namespace", code: "'use server'; const NativeFile = globalThis['File'];", errors: [{ messageId: "serverFile" }] },
    { name: "qualified native type", code: "'use server'; export type Input = globalThis.File;", errors: [{ messageId: "serverFile" }] },
    { name: "buffer named alias", code: "'use server'; import { File as NativeFile } from 'node:buffer'; export type Input = NativeFile;", errors: [{ messageId: "serverFile" }] },
    { name: "buffer named runtime", code: "'use server'; import { File as NativeFile } from 'buffer'; const valid = input instanceof NativeFile;", errors: [{ messageId: "serverFile" }] },
    { name: "buffer namespace", code: "'use server'; import * as binary from 'node:buffer'; const valid = input instanceof binary.File;", errors: [{ messageId: "serverFile" }] },
    { name: "buffer default namespace", code: "'use server'; import binary from 'node:buffer'; const valid = input instanceof binary.File;", errors: [{ messageId: "serverFile" }] },
    { name: "qualified buffer type", code: "'use server'; import * as binary from 'buffer'; export type Input = binary.File;", errors: [{ messageId: "serverFile" }] },
    { name: "destructured global constructor", code: "'use server'; const { File: NativeFile } = globalThis; const value = new NativeFile([], 'item');", errors: [{ messageId: "serverFile" }] },
    { name: "destructured buffer constructor", code: "'use server'; import * as binary from 'buffer'; const { File: NativeFile } = binary;", errors: [{ messageId: "serverFile" }] },
    { name: "multiple directives", code: "'use strict'; 'use server'; const file = File;", errors: [{ messageId: "serverFile" }] },
    { name: "JavaScript upload validation", filename: "server.js", code: "import 'server-only'; const valid = input instanceof File;", errors: [{ messageId: "serverFile" }] },
  ],
});

it("executes the documented upload examples", async () => {
  await verifyRuleExamples(rule);
});
