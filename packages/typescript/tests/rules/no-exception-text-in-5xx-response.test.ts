// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule, { NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION } from "../../src/rules/no-exception-text-in-5xx-response.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const PRODUCTION = "/repo/src/route.ts";
const handler = (body: string, prefix = ""): string => `${prefix}\nfunction handle(){try{run();}catch(error){${body}}}`;
const reply = (body: string, status = "500"): string => `return Response.json(${body},{status:${status}});`;
const action = (body: string, prefix = '"use server";'): string => `${prefix}\nexport async function save(){try{await persist();}catch(error){${body}}}`;
const MESSAGE_HELPER = 'const errorMessage = (error: unknown) => error instanceof Error ? error.message : "Unknown error";';

RULE_TESTER.run("no-exception-text-in-5xx-response", rule, {
  valid: [
    { name: "generic server failure", code: handler(reply("{error:'Internal server error'}")) },
    { name: "public domain error", code: handler(reply("{error:error.message}", "409")) },
    { name: "successful response", code: handler(reply("{error:error.message}", "200")) },
    { name: "unknown status", code: handler(reply("{error:error.message}", "status")) },
    { name: "computed status policy", code: handler(reply("{error:error.message}", "retryable ? 503 : 400")) },
    { name: "status outside HTTP server-error range", code: handler(reply("{error:error.message}", "600")) },
    { name: "fractional status conversion is outside the literal integer boundary", code: handler(reply("{error:error.message}", "500.5")) },
    { name: "reviewed sanitizer owns the public text", code: handler(reply("{error:publicError(error.message)}")) },
    { name: "unrelated object's field", code: handler(reply("{error:result.message}")) },
    { name: "explicit public error code", code: handler(reply("{error:error.code}")) },
    { name: "message only appears in the condition", code: handler(reply("{error:error.message ? 'Unavailable' : 'Failed'}")) },
    { name: "later literal field overrides the raw field", code: handler(reply("{error:error.message,error:'Failed'}")) },
    { name: "custom serializer owns the response", code: handler(reply("{error:error.message,toJSON(){return {error:'Failed'}}}")) },
    { name: "inherited serialization contract", code: handler(reply("{error:error.message,__proto__:serializer}")) },
    { name: "unknown object spread", code: handler(reply("{error:error.message,...publicFields}")) },
    { name: "unknown option spread", code: handler("return Response.json({error:error.message},{status:500,...options});") },
    { name: "unknown computed key could overwrite the raw field", code: handler(reply("{error:error.message,[key]:'Failed'}")) },
    { name: "unreturned construction is not a proven response boundary", code: handler("audit(Response.json({error:error.message},{status:500}));") },
    { name: "response wrapper owns the returned contract", code: handler("return redactResponse(Response.json({error:error.message},{status:500}));") },
    { name: "caught value reassigned", code: handler("error=publicFailure;" + reply("{error:error.message}")) },
    { name: "caught message modified", code: handler("error.message='Public failure';" + reply("{error:error.message}")) },
    { name: "escaped caught value may be sanitized", code: handler("normalize(error);" + reply("{error:error.message}")) },
    { name: "caught alias may sanitize the message", code: handler("const alias=error;alias.message='Public';" + reply("{error:error.message}")) },
    { name: "assigned catch alias may sanitize the message", code: handler("alias=error;alias.message='Public';" + reply("{error:error.message}")) },
    { name: "stored catch value may be sanitized", code: handler("const state={error};normalize(state);" + reply("{error:error.message}")) },
    { name: "array storage escapes the catch value", code: handler("const state=[error];normalize(state);" + reply("{error:error.message}")) },
    { name: "caught receiver may sanitize its message", code: handler("error.sanitize();" + reply("{error:error.message}")) },
    { name: "deleted diagnostic no longer leaks", code: handler("delete error.message;" + reply("{error:error.message}")) },
    { name: "destructuring writes sanitize the field", code: handler("({message:error.message}={message:'Public'});" + reply("{error:error.message}")) },
    { name: "iteration writes replace the field", code: handler("for(error.message of publicMessages){}" + reply("{error:error.message}")) },
    { name: "destructured catch is not the caught object", code: "function handle(){try{run();}catch({publicFailure:error}){return Response.json({error:error.message},{status:500});}}" },
    { name: "statically dead conditional does not return diagnostic text", code: handler(reply("{error:false ? error.message : 'Public'}")) },
    { name: "statically dead logical branch does not return diagnostic text", code: handler(reply("{error:false && error.message}")) },
    { name: "logical condition alone does not return diagnostic text", code: handler(reply("{error:error.message && 'Public'}")) },
    { name: "truthy fixed fallback avoids diagnostic text", code: handler(reply("{error:'Public' || error.message}")) },
    { name: "nonnull fixed fallback avoids diagnostic text", code: handler(reply("{error:'Public' ?? error.message}")) },
    { name: "local response factory owns its behavior", code: handler(reply("{error:error.message}"), "const Response=customResponse;") },
    { name: "parameter shadows the ambient factory", code: "function handle(Response){try{run();}catch(error){return Response.json({error:error.message},{status:500});}}" },
    { name: "unrelated import is not NextResponse", code: handler("return NextResponse.json({error:error.message},{status:500});", "import {NextResponse} from 'another-package';") },
    { name: "explicit local factory override", code: handler(reply("{error:error.message}"), "Response.json=redactedResponse;") },
    { name: "factory passed to an unknown mutator", code: handler(reply("{error:error.message}"), "configure(Response);") },
    { name: "explicit serializer prototype override", code: handler(reply("{error:error.message}"), "Object.prototype.toJSON=publicSerializer;") },
    { name: "prototype mutator owns serialization", code: handler(reply("{error:error.message}"), "Object.defineProperty(Object.prototype,'toJSON',{value:publicSerializer});") },
    { name: "array prototype mutator owns array serialization", code: handler(reply("[error.message]"), "Reflect.set(Array.prototype,'toJSON',publicSerializer);") },
    { name: "factory alias could replace the implementation", code: handler(reply("{error:error.message}"), "const factory=Response;factory.json=redactedResponse;") },
    { name: "global property replaces the implementation", code: handler(reply("{error:error.message}"), "globalThis.Response=customResponse;") },
    { name: "native property mutator replaces the serializer", code: handler(reply("{error:error.message}"), "Object.defineProperty(Response,'json',{value:redactedResponse});") },
    { name: "native global mutator replaces the factory", code: handler(reply("{error:error.message}"), "Object.assign(globalThis,{Response:customResponse});") },
    { name: "assigned factory alias may replace its behavior", code: handler(reply("{error:error.message}"), "factory=Response;factory.json=redactedResponse;") },
    { name: "stored factory alias may replace its behavior", code: handler(reply("{error:error.message}"), "const state={Response};configure(state);") },
    { name: "deleted factory is no longer the native implementation", code: handler(reply("{error:error.message}"), "delete Response.json;") },
    { name: "destructuring overrides the factory", code: handler(reply("{error:error.message}"), "({json:Response.json}={json:redactedResponse});") },
    { name: "tests are excluded", filename: "/repo/test/route.test.ts", code: handler(reply("{error:error.message}")) },
    { name: "generated sources are excluded", filename: "/repo/src/generated/route.ts", code: handler(reply("{error:error.message}")) },
  ].map((entry) => ({ filename: PRODUCTION, ...entry })),
  invalid: [
    { name: "caught message", code: handler(reply("{error:error.message}")) },
    { name: "caught stack", code: handler(reply("{error:error.stack}")) },
    { name: "guarded caught message remains raw", code: handler(reply("{error:error instanceof Error ? error.message : 'Failed'}")) },
    { name: "fallback does not redact a nonempty message", code: handler(reply("{error:error.message || 'Failed'}")) },
    { name: "nullable fallback does not redact the message", code: handler(reply("{error:error.message ?? 'Failed'}")) },
    { name: "logical right side can return diagnostic text", code: handler(reply("{error:ready && error.message}")) },
    { name: "constant true branch returns diagnostic text", code: handler(reply("{error:true ? error.message : 'Failed'}")) },
    { name: "constant null fallback returns diagnostic text", code: handler(reply("{error:null ?? error.message}")) },
    { name: "nested literal payload", code: handler(reply("{failure:{detail:error.message}}")) },
    { name: "array payload", code: handler(reply("[error.message]")) },
    { name: "interpolated message", code: handler(reply("{error:`Failed: ${error.message}`}")) },
    { name: "concatenated stack", code: handler(reply("{error:'Failed: '+error.stack}")) },
    { name: "upper server-error boundary", code: handler(reply("{error:error.message}", "599")) },
    { name: "literal computed field", code: handler(reply("{error:error['message']}")) },
    { name: "stable computed field", code: handler("const field='message';" + reply("{error:error[field]}")) },
    { name: "optional message field", code: handler(reply("{error:error?.message}")) },
    { name: "type assertion preserves the caught binding", code: handler(reply("{error:(error as Error).message}")) },
    { name: "erased status assertion remains literal", code: handler(reply("{error:error.message}", "500 as const")) },
    { name: "optional native factory remains a response boundary", code: handler("return Response?.json({error:error.message},{status:500});") },
    { name: "type assertion on the factory preserves native behavior", code: handler("return (Response as typeof Response).json({error:error.message},{status:500});") },
    { name: "satisfies wrapper preserves the returned response", code: handler("return (Response.json({error:error.message},{status:500}) satisfies Response);") },
    { name: "NextResponse import", code: handler("return NextResponse.json({error:error.message},{status:500});", "import {NextResponse} from 'next/server';") },
    { name: "aliased NextResponse import", code: handler("return Reply.json({error:error.message},{status:502});", "import {NextResponse as Reply} from 'next/server';") },
    { name: "awaited response", code: "async function handle(){try{await run();}catch(error){return await Response.json({error:error.message},{status:500});}}" },
    { name: "captured stable catch binding", code: handler("return () => Response.json({error:error.message},{status:500});") },
    { name: "duplicate fields leak only the last value", code: handler(reply("{error:'Failed',error:error.message}")) },
    { name: "one diagnostic for repeated caught fields", code: handler(reply("{error:error.message,stack:error.stack}")) },
  ].map((entry) => ({ filename: PRODUCTION, ...entry, errors: [{ messageId: "exceptionText" as const }] })),
});

RULE_TESTER.run("no-exception-text-in-5xx-response", rule, {
  valid: [
    { name: "public action failure example", code: NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION.examples[3].files[0].source },
    { name: "client boundary", code: action('return {message:error.message};', '"use client";') },
    { name: "ordinary exported async function", code: action('return {message:error.message};', '') },
    { name: "unexported server helper", code: '"use server"; async function save(){try{await persist();}catch(error){return {message:error.message};}}' },
    { name: "nested local catch cannot become an action boundary", code: '"use server"; export async function save(){return async()=>{try{await persist();}catch(error){return {message:error.message};}};}' },
    { name: "nested callback return remains internal", code: action('return () => ({message:error.message});') },
    { name: "unknown sanitizer helper", code: action('return {message:publicError(error)};') },
    { name: "unknown helper consumer loses mutation proof", code: action('normalize(error);return {message:error.message};') },
    { name: "mutable catch", code: action('error=publicFailure;return {message:error.message};') },
    { name: "mutated catch alias", code: action('const alias=error;alias.message="Public";return {message:error.message};') },
    { name: "mutated result alias", code: action('const result={message:error.message};result.message="Public";return result;') },
    { name: "nested alias escape may sanitize result", code: action('const result={message:error.message};const wrapper={result};normalize(wrapper);return result;') },
    { name: "payload spread has unknown final fields", code: action('return {message:error.message,...publicFields};') },
    { name: "literal override removes caught details", code: action('return {message:error.message,message:"Public"};') },
    { name: "serializer owns public fields", code: action('return {message:error.message,toJSON(){return {message:"Public"}}};') },
    { name: "statically dead branch", code: action('return {message:false?error.message:"Public"};') },
    { name: "message only controls a public selection", code: action('return {message:error.message?"Unavailable":"Failed"};') },
    { name: "helper body mutates its parameter", code: action('return {message:errorMessage(error)};', '"use server"; const errorMessage=(error:unknown)=>{normalize(error);return error.message};') },
    { name: "helper chains remain opaque", code: action('return {message:errorMessage(error)};', '"use server";const raw=(e:unknown)=>e.message;const errorMessage=(error:unknown)=>raw(error);') },
    { name: "shadowed helper binding", code: action('const errorMessage=publicError;return {message:errorMessage(error)};', '"use server";'+MESSAGE_HELPER) },
    { name: "shadowed Error constructor makes helper opaque", code: action('return {message:errorMessage(error)};', '"use server";const Error=PublicError;'+MESSAGE_HELPER) },
    { name: "explicit helper output contract is not inferred", code: action('return {message:errorMessage(error)};', '"use server";const errorMessage=(error:unknown):"Public"=>error.message;') },
    { name: "rebound exported function", code: action('return {message:error.message};')+'save=publicAction;' },
    { name: "reflection invalidates local proof", code: action('eval("error.message = publicText");return {message:error.message};') },
    { name: "prototype serializer override remains uncertain", code: action('return {message:error.message};', '"use server";Object.prototype.toJSON=publicSerializer;') },
    { name: "dead statement branch cannot escape", code: action('if(false)return {message:error.message};return {message:"Public"};') },
    { name: "dead else branch cannot escape", code: action('if(true)return {message:"Public"};else return {message:error.message};') },
    { name: "dead loop cannot escape", code: action('while(false){return {message:error.message};}return {message:"Public"};') },
    { name: "empty for-of cannot expose an action result", code: action('if(error instanceof Error){for(const item of []){return {message:error.message};}}return {message:"Public"};') },
    { name: "empty for-in cannot expose an action result", code: action('if(error instanceof Error){for(const key in {}){return {message:error.message};}}return {message:"Public"};') },
    { name: "unknown for-of iteration remains opaque", code: action('for(const item of items){return {message:error.message};}return {message:"Public"};') },
    { name: "unknown for-in iteration remains opaque", code: action('for(const key in fields){return {message:error.message};}return {message:"Public"};') },
    { name: "async iteration remains opaque", code: action('for await(const item of []){return {message:error.message};}return {message:"Public"};') },
    { name: "earlier unconditional return cannot escape", code: action('return {message:"Public"};return {message:error.message};') },
    { name: "earlier selected return cannot escape", code: action('if(true)return {message:"Public"};return {message:error.message};') },
    { name: "finally overrides the raw result", code: action('try{return {message:error.message};}finally{return {message:"Public"};}') },
    { name: "preceding labeled transfer remains opaque", code: action('done:{return {message:"Public"};}return {message:error.message};') },
    { name: "preceding try transfer remains opaque", code: action('try{return {message:"Public"};}finally{}return {message:error.message};') },
    { name: "preceding loop transfer remains opaque", code: action('while(true){return {message:"Public"};}return {message:error.message};') },
    { name: "break makes a loop result unreachable", code: action('while(true){break;return {message:error.message};}return {message:"Public"};') },
    { name: "preceding exhaustive switch remains opaque", code: action('switch(kind){case "ready":return {message:"Public"};default:return {message:"Public"};}return {message:error.message};') },
    { name: "throwing finally overrides the raw result", code: action('try{return {message:error.message};}finally{throw new Error("Failed");}') },
    { name: "ambient Error mutation invalidates helper purity", code: action('return {message:errorMessage(error)};', '"use server";globalThis.Error=class{static [Symbol.hasInstance](error){error.message="Public";return true;}};'+MESSAGE_HELPER) },
    { name: "native hasInstance mutation invalidates helper purity", code: action('return {message:errorMessage(error)};', '"use server";Object.defineProperty(Error,Symbol.hasInstance,{value:error=>{error.message="Public";return true;}});'+MESSAGE_HELPER) },
    { name: "ambient constructor alias can mutate hasInstance", code: action('return {message:errorMessage(error)};', '"use server";const Constructor=Error;configure(Constructor);'+MESSAGE_HELPER) },
    { name: "whole global escape can replace Error", code: action('return {message:errorMessage(error)};', '"use server";configure(globalThis);'+MESSAGE_HELPER) },
    { name: "exact action suppression", code: action('// eslint-disable-next-line @rule-tester/no-exception-text-in-5xx-response -- reviewed public failure\nreturn {message:error.message};') },
    { name: "test action remains excluded", filename: '/repo/tests/actions.test.ts', code: action('return {message:error.message};') },
    { name: "generated action remains excluded", filename: '/repo/src/generated/actions.ts', code: action('return {message:error.message};') },
  ].map((entry)=>({filename:PRODUCTION,...entry})),
  invalid: [
    { name: "module directive and direct message", code: action('return {message:error.message};') },
    { name: "ordinary guarded action return still escapes", code: action('if(error instanceof Error){return {message:error.message};}return {message:"Public"};') },
    { name: "direct stack", code: action('return {detail:error.stack};') },
    { name: "guarded message", code: action('return {message:error instanceof Error?error.message:"Unknown error"};') },
    { name: "same-module pure helper example", code: NO_EXCEPTION_TEXT_IN_5XX_RESPONSE_DOCUMENTATION.examples[2].files[0].source },
    { name: "function declaration helper", code: action('return {message:errorMessage(error)};', '"use server";function errorMessage(error:unknown){return error instanceof Error?error.message:"Unknown";}') },
    { name: "broad string helper output is still raw", code: action('return {message:errorMessage(error)};', '"use server";function errorMessage(error:unknown):string{return error instanceof Error?error.message:"Unknown";}') },
    { name: "const primitive alias", code: action('const message=error.message;return {message};') },
    { name: "const object alias", code: action('const failure={message:error.message};return failure;') },
    { name: "const caught identity alias", code: action('const failure=error;return {message:failure.message};') },
    { name: "array result", code: action('return [error.message];') },
    { name: "nested literal result", code: action('return {failure:{detail:error.stack}};') },
    { name: "interpolation", code: action('return {message:`Failed: ${error.message}`};') },
    { name: "function directive", code: 'export async function save(){"use server";try{await persist();}catch(error){return {message:error.message};}}' },
    { name: "directive only counts in the prologue", code: '"use strict";"use server";export async function save(){try{await persist();}catch(error){return {message:error.message};}}' },
    { name: "exported async arrow", code: '"use server";export const save=async()=>{try{await persist();}catch(error){return {message:error.message};}};' },
    { name: "default export", code: '"use server";export default async function(){try{await persist();}catch(error){return {message:error.message};}}' },
    { name: "export specifier resolves actual binding", code: '"use server";async function persistAction(){try{await persist();}catch(error){return {message:error.message};}}export {persistAction as save};' },
    { name: "raw finally result can escape", code: action('try{return {message:"Public"};}finally{return {message:error.message};}') },
    { name: "nontransferring finally does not hide a result", code: action('try{return {message:error.message};}finally{recordCompletion();}') },
    { name: "direct native Error construction preserves helper semantics", code: action('return {message:errorMessage(error)};', '"use server";const other=new Error("Other");'+MESSAGE_HELPER) },
  ].map((entry)=>({filename:PRODUCTION,...entry,errors:[{messageId:'serverActionExceptionText' as const}]})),
});

it.each([
  { name: "exported JavaScript Server Action", source: action('return {message:error.message};'), matches: 1 },
  { name: "native response", source: handler(reply("{error:error.message}")), matches: 1 },
  { name: "aliased sanitizer", source: handler("const alias=error;alias.message='Public';" + reply("{error:error.message}")), matches: 0 },
  { name: "unknown consumer", source: handler("normalize(error);" + reply("{error:error.message}")), matches: 0 },
  { name: "NextResponse import", source: handler("return Reply.json({error:error.message},{status:500});", "import {NextResponse as Reply} from 'next/server';"), matches: 1 },
])("native JavaScript parser: $name", ({ source, matches }) => {
  const findings = new Linter().verify(source, [{
    plugins: { sarj: { rules: { privacy: rule } } },
    rules: { "sarj/privacy": "warn" },
  }], { filename: "src/route.js" });
  expect(findings).toHaveLength(matches);
  for (const finding of findings) expect(finding).toMatchObject({ ruleId: "sarj/privacy", severity: 1 });
});

it("native Response.json exposes the caught message while a generic response keeps it private", async () => {
  const marker = "internal-diagnostic-marker";
  let unsafe: Response;
  try {
    throw new Error(marker);
  } catch (error) {
    unsafe = Response.json({ error: error instanceof Error ? error.message : "Failed" }, { status: 500 });
  }
  expect(unsafe.status).toBe(500);
  expect(await unsafe.json()).toStrictEqual({ error: marker });
  const safe = Response.json({ error: "Internal server error" }, { status: 500 });
  expect(await safe.text()).not.toContain(marker);
});
