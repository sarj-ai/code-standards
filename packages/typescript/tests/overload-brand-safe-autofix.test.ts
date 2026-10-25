// vitest: shared-module-graph
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

import * as parser from "@typescript-eslint/parser";
import { Linter } from "eslint";
import ts from "typescript";
import { expect, it } from "vitest";

import rule from "../src/rules/prefer-nominal-id-types.js";

const SOURCE =
  "export type AccountId = string & { readonly account: unique symbol };\nexport type InvoiceId = string & { readonly invoice: unique symbol };\nexport function load(accountId: AccountId, invoiceId: InvoiceId): void;\nexport function load(accountId: string, invoiceId: string): void {}";
const FIXED = SOURCE.replace(
  "accountId: string, invoiceId: string",
  "accountId: AccountId, invoiceId: InvoiceId",
);

function apply(source: string): ReturnType<Linter["verifyAndFix"]> {
  return new Linter().verifyAndFix(
    source,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser },
        plugins: { local: { rules: { check: rule } } },
        rules: { "local/check": "error" },
      },
    ],
    { filename: "src/ids.ts" },
  );
}

it.each(["\n", "\r\n"])(
  "reuses the existing overload and converges with %s endings",
  (ending) => {
    const source = SOURCE.replaceAll("\n", ending);
    const expected = FIXED.replaceAll("\n", ending);
    const result = apply(source);
    expect(result.fixed).toBe(true);
    expect(result.output).toBe(expected);
    expect(result.messages).toEqual([]);
    expect(apply(expected).fixed).toBe(false);
    expect(apply(expected).messages).toEqual([]);
  },
);

it("uses native UTF-16 ranges and the authored Unicode alias spelling", () => {
  const source = SOURCE.replaceAll("AccountId", "ÄccountId").replaceAll(
    "InvoiceId",
    "İnvoiceId",
  );
  const expected = FIXED.replaceAll("AccountId", "ÄccountId").replaceAll(
    "InvoiceId",
    "İnvoiceId",
  );
  expect(apply(source).output).toBe(expected);
  expect(apply(expected).fixed).toBe(false);
});

it.each([
  SOURCE.replace("export type AccountId", "type AccountId"),
  SOURCE.replace("export type InvoiceId", "type InvoiceId"),
  SOURCE.replace("type AccountId =", "type AccountId<T> ="),
  SOURCE.replace("readonly account", "account"),
  SOURCE.replace("unique symbol", "symbol"),
  SOURCE.replace("readonly account:", "readonly account?:"),
  SOURCE.replace("readonly account:", "readonly [account]:"),
  SOURCE.replace("string &", "number &"),
  SOURCE.replace("invoiceId: InvoiceId", "invoiceId: AccountId"),
  SOURCE.replace("invoiceId: InvoiceId", "invoiceId: string"),
  SOURCE.replace("invoiceId: InvoiceId", "otherId: InvoiceId"),
  SOURCE.replace("accountId: AccountId", "accountId: AccountId<string>"),
  SOURCE.replace("load(accountId: AccountId", "load<T>(accountId: AccountId"),
  SOURCE.replace("load(accountId: string", "load<T>(accountId: string"),
  SOURCE.replace("accountId: AccountId", "accountId?: AccountId"),
  SOURCE.replace("accountId: string", "accountId?: string"),
  SOURCE.replace("accountId: string", "accountId: string = ''"),
  SOURCE.replace("invoiceId: string", "...invoiceId: string[]"),
  SOURCE.replace("void {}", "void { return; }"),
  SOURCE.replace("void {}", "void { eval(''); }"),
  SOURCE.replace("void {}", "void { throw Error(); }"),
  SOURCE.replace(
    "export function load(accountId: string",
    "function load(accountId: string",
  ),
  SOURCE.replace(
    "export function load(accountId: string",
    "export async function load(accountId: string",
  ),
  SOURCE.replace(
    "export function load(accountId: string",
    "export function* load(accountId: string",
  ),
  SOURCE.replace(": void;", ": string;"),
  SOURCE.replace("void {}", "unknown {}"),
  SOURCE.replace(
    "export function load(accountId: AccountId, invoiceId: InvoiceId): void;\n",
    "",
  ),
  SOURCE.replace(
    "export function load(accountId: string",
    "export function other(accountId: string",
  ),
  "import 'setup';\n" + SOURCE,
  "// preserve rationale\n" + SOURCE,
  SOURCE + "\nexport const extra = 1;",
  SOURCE +
    "\nexport function load(accountId: AccountId, invoiceId: InvoiceId): void;",
  SOURCE.replace("export type AccountId", "export declare type AccountId"),
])(
  "keeps unproven brands, overloads and implementation contracts manual",
  (source) => {
    const result = apply(source);
    expect(result.fixed).toBe(false);
    expect(result.output).toBe(source);
  },
);

it("retains exactly identical emitted JavaScript and runtime behavior", () => {
  const compile = (source: string): string =>
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ESNext,
      },
    }).outputText;
  const original = compile(SOURCE);
  const fixed = compile(apply(SOURCE).output);
  expect(fixed).toBe(original);
  const oracle =
    "[exports.load.length,exports.load.name,exports.load('a','b'),exports.load(new Proxy({}, {get(){throw Error('observed')}}),null)]";
  expect(
    runInNewContext(`${fixed}\nJSON.stringify(${oracle});`, { exports: {} }),
  ).toBe(
    runInNewContext(`${original}\nJSON.stringify(${oracle});`, { exports: {} }),
  );
});

it("strictly typechecks both versions with identical JavaScript and public declarations", () => {
  const virtual = new Map([
    [
      fileURLToPath(new URL("../autofix-overload-before.ts", import.meta.url)),
      SOURCE,
    ],
    [
      fileURLToPath(new URL("../autofix-overload-after.ts", import.meta.url)),
      FIXED,
    ],
  ]);
  const options: ts.CompilerOptions = {
    strict: true,
    declaration: true,
    skipLibCheck: true,
    types: [],
    target: ts.ScriptTarget.ESNext,
    module: ts.ModuleKind.ESNext,
  };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  const exists = host.fileExists.bind(host);
  host.fileExists = (filename) => virtual.has(filename) || exists(filename);
  host.getSourceFile = (filename, version, onError, fresh) => {
    const source = virtual.get(filename);
    return source === undefined
      ? original(filename, version, onError, fresh)
      : ts.createSourceFile(filename, source, version, true);
  };
  const outputs = new Map<string, string>();
  host.writeFile = (filename, text) => {
    outputs.set(filename, text);
  };
  const program = ts.createProgram([...virtual.keys()], options, host);
  expect(ts.getPreEmitDiagnostics(program)).toEqual([]);
  expect(program.emit().emitSkipped).toBe(false);
  const output = (suffix: string): string | undefined =>
    [...outputs].find(([name]) => name.endsWith(suffix))?.[1];
  for (const extension of [".js", ".d.ts"]) {
    const before = output(`autofix-overload-before${extension}`);
    expect(before).toBeDefined();
    expect(output(`autofix-overload-after${extension}`)).toBe(before);
  }
  expect(output("autofix-overload-before.d.ts")).not.toContain(
    "accountId: string",
  );
});
