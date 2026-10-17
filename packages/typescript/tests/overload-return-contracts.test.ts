import { join } from "node:path";
import { runInNewContext } from "node:vm";

import ts from "typescript";
import { expect, it } from "vitest";

const OVERLOADS = 'function load(kind:"text"):{kind:"text",text:string};function load(kind:"count"):{kind:"count",count:number};';
const BROAD_RESULT = '{kind:string,text?:string,count?:number}';
const BAD = OVERLOADS+`function load(kind:"text"|"count"):${BROAD_RESULT}{return kind==="text"?{kind:"count",count:1}:{kind:"text",text:"ok"};}load("text").text.toUpperCase();`;
const GOOD = OVERLOADS+`function load(kind:"text"|"count"):${BROAD_RESULT}{return kind==="text"?{kind:"text",text:"ok"}:{kind:"count",count:1};}load("text").text.toUpperCase();`;

it("native overload checking accepts an envelope that swaps the public case results", () => {
  expect(diagnostics(BAD)).toEqual([]);
  expect(() => { execute(BAD); }).toThrow("Cannot read properties of undefined");
});

it("matching case results preserve both the native contract and runtime behavior", () => {
  expect(diagnostics(GOOD)).toEqual([]);
  expect(() => { execute(GOOD); }).not.toThrow();
});

it("a checked case map rejects a swapped variant at its construction", () => {
  const source = 'type Cases={text:{kind:"text",text:string};count:{kind:"count",count:number}};const cases:Cases={text:{kind:"count",count:1},count:{kind:"text",text:"ok"}};';
  expect(diagnostics(source)).toContain(2322);
});

it("a checked case map retains a usable dependent result without a type assertion", () => {
  const source = 'type Cases={text:{kind:"text",text:string};count:{kind:"count",count:number}};const cases:Cases={text:{kind:"text",text:"ok"},count:{kind:"count",count:1}};function load<K extends keyof Cases>(kind:K):Cases[K]{return cases[kind];}load("text").text.toUpperCase();';
  expect(diagnostics(source)).toEqual([]);
  expect(() => { execute(source); }).not.toThrow();
});

it("loose null checking can make a later null overload unreachable at a call", () => {
  const source = 'function f(v:"a"):1;function f(v:null):2;function f(v:"a"|null):number{return v==="a"?1:1;}const value:1=f(null);if(value!==1)throw new Error("unexpected overload result");';
  expect(diagnostics(source, false)).toEqual([]);
  expect(diagnostics(source, true)).toContain(2322);
  expect(() => { execute(source); }).not.toThrow();
});

function diagnostics(source: string, strictNullChecks = true): readonly number[] {
  const filename = join(import.meta.dirname, "fixtures", "overload-proof.ts");
  const options: ts.CompilerOptions = { noEmit: true, strict: true, strictNullChecks, target: ts.ScriptTarget.ES2022, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, source, version, true) : original(path, version, onError, create);
  return ts.getPreEmitDiagnostics(ts.createProgram([filename], options, host)).map((diagnostic) => diagnostic.code);
}

function execute(source: string): void {
  runInNewContext(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText);
}
