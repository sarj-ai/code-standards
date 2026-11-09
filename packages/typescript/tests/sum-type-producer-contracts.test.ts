import { join } from "node:path";
import { runInNewContext } from "node:vm";

import ts from "typescript";
import { expect, it } from "vitest";

function nativeContract(source: string): { readonly codes: readonly number[]; readonly emitted: string } {
  const file = join(import.meta.dirname, "fixtures", "sum-type-contract.ts");
  const options: ts.CompilerOptions = { strict: true, exactOptionalPropertyTypes: true, noUncheckedIndexedAccess: true, skipLibCheck: true, types: [], target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (requested, languageVersion, onError, fresh) => requested === file
    ? ts.createSourceFile(file, source, languageVersion, true)
    : original(requested, languageVersion, onError, fresh);
  const program = ts.createProgram([file], options, host);
  return {
    codes: ts.getPreEmitDiagnostics(program).map(diagnostic => diagnostic.code),
    emitted: ts.transpileModule(source, { compilerOptions: options }).outputText,
  };
}

it("a dispatcher union preserves narrowing and rejects incomplete variants", () => {
  const producer = 'function job(command:string):Job{switch(command){case "start":return {phase:"queued",ticket:"t"};default:return {phase:"complete"};}}';
  const consume = 'const state=job("start");if(state.phase==="queued")state.ticket.toUpperCase();';
  const flat = 'type Job={phase:"queued"|"complete";ticket?:string};';
  const variants = 'type Job={phase:"queued";ticket:string}|{phase:"complete"};';
  expect(nativeContract(flat + producer).codes).toEqual([]);
  expect(nativeContract(flat + producer + consume).codes).toEqual([18048]);
  expect(nativeContract(variants + producer + consume).codes).toEqual([]);
  expect(nativeContract(variants + 'const incomplete:Job={phase:"queued"};').codes).toEqual([2322]);
});

it("grouped switch labels and a default preserve native result behavior", () => {
  const result = nativeContract('function job(command:string):{phase:"queued";ticket:string}|{phase:"complete"}{switch(command){case "start":case "retry":return {phase:"queued",ticket:command};default:return {phase:"complete"};}}for(const command of ["start","retry","other"]){const state=job(command);if(state.phase==="queued"&&state.ticket!==command)throw Error("payload lost");if(command==="other"&&state.phase!=="complete")throw Error("default lost");}');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("native array membership accepts a concrete element outside a promised text domain", () => {
  const result = nativeContract('function texts(value:unknown):value is string[]{return Array.isArray(value);}const value:unknown=[1];if(texts(value))value[0]?.toUpperCase();');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).toThrow("toUpperCase");
});

it("a complete content validator preserves legal typed-array boundary guards", () => {
  const result = nativeContract('function texts(value:unknown):value is string[]{return Array.isArray(value)&&value.every((item:unknown)=>typeof item==="string");}for(const value of [[1],["ok"],null]){if(texts(value))value[0]?.toUpperCase();}');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("a visible native namespace replacement can change the check into a complete validator", () => {
  const result = nativeContract('const native=Array.isArray;Array.isArray=(value:unknown):value is string[]=>native(value)&&value.every((item:unknown)=>typeof item==="string");function texts(value:unknown):value is string[]{return Array.isArray(value);}if(texts([1]))throw Error("numeric element admitted");if(!texts(["ok"]))throw Error("valid text rejected");');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("an opaque prototype constructor can expose the same native array API", () => {
  const result = nativeContract('const Native=Object.getPrototypeOf([]).constructor;const raw:(value:unknown)=>value is unknown[]=Native.isArray;Native.isArray=(value:unknown):value is string[]=>raw(value)&&value.every((item:unknown)=>typeof item==="string");function texts(value:unknown):value is string[]{return Array.isArray(value);}if(texts([1]))throw Error("numeric element admitted");if(!texts(["ok"]))throw Error("valid text rejected");');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("native reflection can extract an array constructor without an Array namespace read", () => {
  const result = nativeContract('const Native=Reflect.get([],"constructor");const raw:(value:unknown)=>value is unknown[]=Native.isArray;Native.isArray=(value:unknown):value is string[]=>raw(value)&&value.every((item:unknown)=>typeof item==="string");function texts(value:unknown):value is string[]{return Array.isArray(value);}if(texts([1]))throw Error("numeric element admitted");if(!texts(["ok"]))throw Error("valid text rejected");');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("a structural object view can retain the same native array constructor", () => {
  const result = nativeContract('const holder:object=[];const Constructor=holder.constructor;Object.defineProperty(Constructor,"isArray",{value:(value:unknown):value is string[]=>value instanceof Constructor&&(value as unknown[]).every((item:unknown)=>typeof item==="string")});function texts(value:unknown):value is string[]{return Array.isArray(value);}if(texts([1]))throw Error("numeric element admitted");if(!texts(["ok"]))throw Error("valid text rejected");');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("object destructuring can expose the same constructor through a structural view", () => {
  const result = nativeContract('const holder:object=[];const {constructor:Native}=holder;const raw=(Native as ArrayConstructor).isArray;const every=(Native as ArrayConstructor).prototype.every;Object.assign(Native,{isArray:(value:unknown):value is string[]=>raw(value)&&every.call(value,(item:unknown)=>typeof item==="string")});function texts(value:unknown):value is string[]{return Array.isArray(value);}if(texts([1]))throw Error("numeric element admitted");if(!texts(["ok"]))throw Error("valid text rejected");');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("a switch default cannot emit a case whose input already matched another label", () => {
  const result = nativeContract('type Job={phase:"queued"|"complete";ticket?:string};function job(command:string):Job{switch(command){case "start":return{phase:"queued",ticket:"t"};default:if(command==="start")return{phase:"complete"};return{phase:"queued",ticket:"t"};}}for(const command of ["start","other",""]){if(job(command).phase!=="queued")throw Error("unreachable tag emitted");}');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("a same-named parameter does not expose an overload implementation default", () => {
  const result = nativeContract('type Job={phase:"queued"|"complete";ticket?:string};function job(command:"start",job?:unknown):Job;function job(command:string,job?:unknown):Job{switch(command){case "start":return{phase:"queued",ticket:"t"};default:return{phase:"complete"};}}if(job("start").phase!=="queued")throw Error("public input lost");');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});

it("three failure dispositions preserve partial results and reject only the crossed flag pair", () => {
  const flat = '{ retriable: boolean; persisted: boolean }';
  const variants = '{ retriable: false; persisted: true } | { retriable: true; persisted: false } | { retriable: false; persisted: false }';
  const producer = `function failure(retry: boolean, saved: boolean): ${flat} { return saved ? { retriable: false, persisted: true } : retry ? { retriable: true, persisted: false } : { retriable: false, persisted: false }; }`;
  const fixed = producer.replace(flat, variants);
  expect(nativeContract(producer).codes).toEqual([]);
  expect(nativeContract(fixed).codes).toEqual([]);
  expect(nativeContract(`type State = ${variants}; const crossed: State = { retriable: true, persisted: true };`).codes).toEqual([2322]);
  const consume = 'for (const a of [true,false]) for (const b of [true,false]) { const state = failure(a,b); if (state.persisted) { const terminal: false = state.retriable; } }';
  expect(nativeContract(fixed + consume).codes).toEqual([]);
  expect(nativeContract(producer).emitted).toBe(nativeContract(fixed).emitted);
});

it("async assimilation can fulfill with a state absent from returned thenable carriers", async () => {
  const result = nativeContract('type R={left:boolean;right:boolean;then?:unknown};function settle(resolve:(value:R)=>void):void{resolve({left:true,right:true});}async function state(flag:boolean):Promise<R>{return flag?{left:true,right:false,then:settle}:{left:false,right:true,then:settle};}state(true).then(value=>JSON.stringify(value));');
  expect(result.codes).toEqual([]);
  expect(await runInNewContext(result.emitted)).toBe('{"left":true,"right":true}');
});

it("a broad assertion still requires a broad function return annotation", () => {
  const flat = '{left:boolean;right:boolean}';
  const variants = '{left:true;right:false}|{left:false;right:true}';
  const source = `type Flat=${flat};function state(flag:boolean):${flat}{return flag?({left:true,right:false} as Flat):({left:false,right:true} as Flat);}`;
  expect(nativeContract(source).codes).toEqual([]);
  expect(nativeContract(source.replace(`):${flat}`, `):${variants}`)).codes).toContain(2322);
});

it("a Boolean-pair union retains independent optional and nullable payloads", () => {
  const flat = '{left:boolean;right:boolean;trace?:string|null}';
  const variants = '{left:true;right:false;trace?:string|null}|{left:false;right:true;trace?:string|null}';
  const source = `function state(flag:boolean):${flat}{return flag?{left:true,right:false,trace:null}:{left:false,right:true};}`;
  const fixed = source.replace(flat, variants);
  expect(nativeContract(source).codes).toEqual([]);
  expect(nativeContract(fixed).codes).toEqual([]);
  expect(nativeContract(source).emitted).toBe(nativeContract(fixed).emitted);
  expect(nativeContract(`type State=${variants};const withoutTrace:State={left:true,right:false};const nullable:State={left:false,right:true,trace:null};`).codes).toEqual([]);
  expect(nativeContract(`type State=${variants};const crossed:State={left:true,right:true};`).codes).toContain(2322);
});

it("direct eval in a default parameter can erase switch input witnesses", () => {
  const result = nativeContract('function state(command:string,force:undefined=eval("command=\\\"start\\\"")):{phase:"queued"|"complete";ticket?:string}{switch(command){case "start":return{phase:"queued",ticket:"t"};default:return{phase:"complete"};}}for(const command of ["start","other",""]){if(state(command).phase!=="queued")throw Error("input was not replaced");}');
  expect(result.codes).toEqual([]);
  expect(() => { runInNewContext(result.emitted); }).not.toThrow();
});
