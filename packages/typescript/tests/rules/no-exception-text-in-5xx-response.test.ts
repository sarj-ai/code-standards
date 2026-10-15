// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/no-exception-text-in-5xx-response.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const PRODUCTION = "/repo/src/route.ts";
const handler = (body: string, prefix = ""): string => `${prefix}\nfunction handle(){try{run();}catch(error){${body}}}`;
const reply = (body: string, status = "500"): string => `return Response.json(${body},{status:${status}});`;

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

it.each([
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
