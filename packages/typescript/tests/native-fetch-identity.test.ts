import * as tsParser from "@typescript-eslint/parser";
import { simpleTraverse } from "@typescript-eslint/typescript-estree";
import { AST_NODE_TYPES, type TSESTree } from "@typescript-eslint/utils";
import { Linter } from "eslint";
import { describe, expect, it } from "vitest";

import rawFetch from "../src/rules/no-raw-fetch-outside-clients.js";
import timeout from "../src/rules/require-fetch-timeout.js";

function diagnostics(source: string, linter = new Linter(), filename = "src/routes/handler.ts"): Linter.LintMessage[] {
  return linter.verify(source, {
    files: ["**/*.ts"],
    languageOptions: { parser: tsParser },
    plugins: { local: { rules: { raw: rawFetch as never, timeout: timeout as never } } },
    rules: { "local/raw": "error", "local/timeout": "error" },
  } as never, filename);
}

function lastCallLocation(source: string) {
  const parsed = tsParser.parseForESLint(source, { loc: true, range: true });
  const calls: TSESTree.CallExpression[] = [];
  simpleTraverse(parsed.ast, {
    visitorKeys: parsed.visitorKeys,
    enter(node) {
      if (node.type === AST_NODE_TYPES.CallExpression) calls.push(node);
    },
  });
  let last: TSESTree.CallExpression | undefined;
  for (const call of calls) {
    if (last === undefined || call.range[0] > last.range[0]) last = call;
  }
  if (last === undefined) throw new Error("The fixture has no target call.");
  return { line: last.loc.start.line, column: last.loc.start.column + 1, endLine: last.loc.end.line, endColumn: last.loc.end.column + 1 };
}

describe("shared native fetch identity", () => {
  it.each([
    "fetch('/x');",
    "globalThis.fetch('/x');",
    "window['fetch']('/x');",
    "self[`fetch`]('/x');",
    "const key='fetch'; globalThis[key]('/x');",
    "globalThis['fetch' as const]('/x');",
    "(globalThis as typeof globalThis).fetch('/x');",
    "fetch?.('/x');",
    "globalThis.fetch?.('/x');",
    "const perform=fetch; perform('/x');",
    "const perform=globalThis.fetch; const request=perform; request('/x');",
    "const {fetch: request}=globalThis; request('/x');",
    "const {fetch}=window; fetch('/x');",
    "const {['fetch' as const]: request}=(self as typeof self); request('/x');",
    "globalThis.other=1; const perform=globalThis.fetch; perform('/x');",
    "delete self.other; fetch('/x');",
    "const marker=typeof fetch; fetch('/x');",
    "if(typeof globalThis!=='undefined') fetch('/x');",
    "if(typeof window!=='undefined') fetch('/x');",
    "if(typeof self!=='undefined') fetch('/x');",
    "if(typeof global!=='undefined') fetch('/x');",
    "if(typeof (window as typeof window)!=='undefined') fetch('/x');",
    "function run(globalThis) { if(typeof globalThis!=='undefined') fetch('/x'); }",
    "function run(window) { if(typeof window!=='undefined') fetch('/x'); }",
    "function run(self) { if(typeof self!=='undefined') fetch('/x'); }",
    "function run(global) { if(typeof global!=='undefined') fetch('/x'); }",
    "const transport={constructor: custom}; fetch('/x');",
    "const key='constructor'; const transport={[key]: custom}; fetch('/x');",
    "const perform=fetch; const marker=typeof perform; perform('/x');",
    "type Native=typeof fetch; const perform: Native=fetch; type Captured=typeof perform; perform('/x');",
    "type Native=typeof globalThis.fetch; fetch('/x');",
    "type Native=typeof window.fetch; fetch('/x');",
    "const request=fetch; type Native=typeof request.call; request('/x');",
    "function unrelated(globalThis, fetch, eval, Function) { globalThis.fetch=fetch; eval(); Function(); } fetch('/x');",
    "function unrelated(window, self, global) { window.fetch=custom; self.fetch=custom; global.fetch=custom; } fetch('/x');",
  ])("retains both owners for a proved native call: %s", (source) => {
    const messages = diagnostics(source);
    expect(messages.map(({ ruleId }) => ruleId).sort()).toEqual(["local/raw", "local/timeout"]);
    expect(messages.every(({ severity, fix, suggestions }) =>
      severity === 2 && fix === undefined && suggestions === undefined)).toBe(true);
    const location = lastCallLocation(source);
    for (const message of messages) {
      expect(message).toMatchObject({ ...location, messageId: message.ruleId === "local/raw" ? "rawFetch" : "missingSignal" });
    }
  });

  it.each([
    "type Native=typeof globalThis.fetch; globalThis.fetch=custom; fetch('/x');",
    "const request=fetch; type Native=typeof request.call; configure(request); request('/x');",
    "type Native=typeof globalThis.fetch; Function('globalThis.fetch=custom')(); fetch('/x');",
    "type Native=typeof globalThis.fetch; eval('globalThis.fetch=custom'); fetch('/x');",
    "function run(window) { type Native=typeof window.fetch; (window as typeof window).fetch('/x'); }",
    "type Native=typeof globalThis.fetch; const {constructor: Compile}=function(){}; Compile('globalThis.fetch=custom')(); fetch('/x');",
  ])("retains runtime uncertainty beside an erased type query: %s", (source) => {
    expect(diagnostics(source)).toEqual([]);
  });

  it.each([
    "globalThis.fetch=custom; globalThis.fetch('/x');",
    "fetch=custom; const perform=fetch; perform('/x');",
    "fetch ||= custom; fetch('/x');",
    "({fetch}=replacement); fetch('/x');",
    "window.fetch=custom; const {fetch: request}=globalThis; request('/x');",
    "self['fetch']=custom; fetch('/x');",
    "global.fetch=custom; fetch('/x');",
    "const perform=globalThis.fetch; globalThis.fetch=custom; perform('/x');",
    "fetch('/x'); window.fetch=custom;",
    "delete self['fetch']; fetch('/x');",
    "globalThis.fetch++; fetch('/x');",
    "const key='fetch'; delete window[key]; fetch('/x');",
    "Reflect.set(globalThis,'fetch',custom); fetch('/x');",
    "Reflect.deleteProperty(self,'fetch'); fetch('/x');",
    "Object.assign(globalThis,{fetch:custom}); fetch('/x');",
    "Object.defineProperty(window,'fetch',{value:custom}); fetch('/x');",
    "const realm=globalThis; realm.fetch=custom; fetch('/x');",
    "configure(globalThis); fetch('/x');",
    "function realm() { return window; } fetch('/x');",
    "const holder={...self}; fetch('/x');",
    "globalThis[key]=custom; fetch('/x');",
    "const realm=globalThis.window; realm.fetch=custom; fetch('/x');",
    "const perform=fetch; configure(perform); perform('/x');",
    "const perform=fetch; const request=perform; configure(request); perform('/x');",
    "const perform=fetch; perform.extra=custom; perform('/x');",
    "const perform=fetch; delete perform.extra; perform('/x');",
    "const perform=fetch; perform.call(null,'/x'); fetch('/x');",
    "export const perform=fetch; perform('/x');",
    "const perform=fetch; export {perform}; perform('/x');",
    "const perform=fetch; function expose() { return perform; } perform('/x');",
    "const perform=fetch; const holder={perform}; perform('/x');",
    "let perform=fetch; perform('/x');",
    "const {fetch:request,...rest}=globalThis; request('/x');",
    "const {fetch:request,eval:execute}=globalThis; request('/x');",
    "const {fetch:request,window:realm}=globalThis; request('/x');",
    "const {fetch:request=custom}=globalThis; request('/x');",
    "const {fetch:request,[key]:value}=globalThis; request('/x');",
    "const {fetch:{call:request}}=globalThis; request('/x');",
    "eval('globalThis.fetch=custom'); fetch('/x');",
    "Function('globalThis.fetch=custom')(); fetch('/x');",
    "globalThis.eval('fetch=custom'); fetch('/x');",
    "window['Function']('fetch=custom')(); fetch('/x');",
    "const create=object.constructor; fetch('/x');",
    "const {constructor: Compile}=function(){}; Compile('globalThis.fetch = async () => 1')(); fetch('/x');",
    "const {['constructor']: Compile}=function(){}; Compile('globalThis.fetch = async () => 1')(); fetch('/x');",
    "const key='constructor'; const {[key]: Compile}=function(){}; Compile('globalThis.fetch = async () => 1')(); fetch('/x');",
    "const {['constructor' as const]: Compile}=function(){}; Compile('globalThis.fetch = async () => 1')(); fetch('/x');",
    "let Compile; ({constructor: Compile}=function(){}); Compile('globalThis.fetch = async () => 1')(); fetch('/x');",
    "import request from './transport'; request('/x');",
    "function run(fetch) { fetch('/x'); }",
    "function run(globalThis) { globalThis.fetch('/x'); }",
    "const perform=()=>fetch; perform('/x');",
    "const first=second; const second=first; first('/x');",
  ])("abstains for visible uncertainty or unproved origin: %s", (source) => {
    expect(diagnostics(source)).toEqual([]);
  });

  it("keeps the eight-binding lexical boundary", () => {
    const aliases = Array.from({ length: 9 }, (_, index) =>
      `const request${index}=${index === 0 ? "fetch" : `request${index - 1}`};`).join(" ");
    expect(diagnostics(`${aliases} request7('/x');`).map(({ ruleId }) => ruleId).sort()).toEqual(["local/raw", "local/timeout"]);
    expect(diagnostics(`${aliases} request8('/x');`)).toEqual([]);
  });

  it("shares whole-file results across calls and keeps caches specific to SourceCode", () => {
    const linter = new Linter();
    const source = "const perform=globalThis.fetch; perform('/x'); fetch('/y');";
    expect(diagnostics(source, linter)).toHaveLength(4);
    expect(diagnostics(`window.fetch=custom; ${source}`, linter)).toEqual([]);
    expect(diagnostics(source, linter)).toHaveLength(4);
  });

  it("preserves call-site suppression for aliases", () => {
    expect(diagnostics("const request=globalThis.fetch;\n// eslint-disable-next-line local/raw, local/timeout\nrequest('/x');")).toEqual([]);
  });

  it.each(["src/clients/transport.ts", "src/handler.test.ts", "scripts/probe.ts", "src/__testfixtures__/input.ts"])(
    "preserves existing path exclusions: %s", (filename) => {
      const messages = diagnostics("const request=globalThis.fetch; request('/x');", new Linter(), filename);
      expect(messages.filter(({ ruleId }) => ruleId === "local/raw")).toEqual([]);
      if (filename !== "src/clients/transport.ts") expect(messages).toEqual([]);
    },
  );
});
