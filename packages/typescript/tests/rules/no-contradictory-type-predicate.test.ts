import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import ts from "typescript";
import { afterAll, describe, it } from "vitest";

import rule, { NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION } from "../../src/rules/no-contradictory-type-predicate.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });

TESTER.run("no-contradictory-type-predicate", rule, {
  valid: [
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({
      name: "fixed private predicate retains line terminators and converges " + JSON.stringify(ending),
      code: `export {}; function check(v: unknown): boolean${ending} { return typeof v === "number"; }`,
    })),
    { name: "fixed record predicate converges with boolean return", code: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): boolean { return typeof v === \"object\" && v !== null; }" },
    { name: "overload owns the separate record predicate contract", code: "export type Kept = Account; type Account = { id: string }; function check(v: Account): v is Account; function check(v: unknown): v is Account { return typeof v === \"object\"; }" },
    { name: "record property validation", code: 'type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === "object" && v !== null && "id" in v && typeof v.id === "string"; }' },
    { name: "optional-only record has no required field witness", code: 'type Account = { id?: string }; function check(v: unknown): v is Account { return typeof v === "object" && v !== null; }' },
    { name: "index contract is not a named record", code: 'type Bag = Record<string, unknown>; function check(v: unknown): v is Bag { return typeof v === "object" && v !== null; }' },
    { name: "generic record is outside the witness proof", code: 'type Account<T> = { id: T }; function check(v: unknown): v is Account<string> { return typeof v === "object" && v !== null; }' },
    { name: "class construction has a separate runtime contract", code: 'class Account { id = ""; } function check(v: unknown): v is Account { return typeof v === "object" && v !== null; }' },
    { name: "public consistent predicate", code: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION.examples[0].files[0].source },
    { name: "overload publishes a sound narrower predicate", code: 'function isText(v: string | number): v is string; function isText(v: unknown): v is string | number { return typeof v === "string"; }' },
    { name: "overload publishes only a boolean contract", code: 'function isText(v: string): boolean; function isText(v: unknown): v is string | number { return typeof v === "string"; }' },
    { name: "contextual callback has a narrower input", code: 'const isText: (v: string) => boolean = (v: unknown): v is string | number => typeof v === "string";' },
    { name: "contextual function expression preserves exposed domain", code: 'const isText: (v: string) => boolean = function(v: unknown): v is string | number { return typeof v === "string"; };' },
    { name: "contextual object method preserves its callback contract", code: 'const adapter: { isText(v: string): boolean } = { isText(v: unknown): v is string | number { return typeof v === "string"; } };' },
    ...[
      ["broad number", 'function check(v: unknown): v is number { return typeof v === "number"; }'],
      ["broad boolean", 'function check(v: unknown): v is boolean { return typeof v === "boolean"; }'],
      ["broad bigint", 'function check(v: unknown): v is bigint { return typeof v === "bigint"; }'],
      ["broad symbol", 'function check(v: unknown): v is symbol { return typeof v === "symbol"; }'],
      ["broad undefined", 'function check(v: unknown): v is undefined { return typeof v === "undefined"; }'],
      ["finite input includes tested kind", 'function check(v: string | number): v is number { return typeof v === "number"; }'],
      ["nullable input permits a string check", 'function check(v: string | null): v is string { return typeof v === "string"; }'],
      ["closed input makes a literal typeof predicate total", 'function check(v: "ready" | null): v is "ready" { return typeof v === "string"; }'],
      ["closed literal alias retains the actual input domain", 'type State="ready"|"done";function check(v:State|number):v is State{return typeof v==="string";}'],
      ["finite numeric input matches the whole target", 'function check(v:1|2|null):v is 1|2{return typeof v==="number";}'],
      ["finite boolean input matches its singleton target", 'function check(v:true|null):v is true{return typeof v==="boolean";}'],
      ["finite bigint input matches its whole target", 'function check(v:1n|2n|null):v is 1n|2n{return typeof v==="bigint";}'],
      ["numeric enum input supplies only its declared members", 'enum E{One=1,Two=2}function check(v:E|null):v is E{return typeof v==="number";}'],
      ["never input has no admissible successful witness", 'function check(v:never):v is never{return typeof v==="number";}'],
      ["false predicate has no successful typeof witness", 'function check(v:unknown):v is never{return false;}'],
      ["non-null object input does not admit null", 'function check(v:object):v is object{return typeof v==="object";}'],
      ["complete object check includes functions and excludes null", 'function check(v:unknown):v is object{return (typeof v==="object"&&v!==null)||typeof v==="function";}'],
      ["nullable intrinsic object target is not a non-null promise", 'function check(v:unknown):v is object|null{return typeof v==="object";}'],
      ["closed literal equality is not a primitive-wide check", 'function check(v:unknown):v is "ready"{return v==="ready";}'],
      ["literal contract in an overload remains independently owned", 'function check(v:"ready"|null):v is "ready";function check(v:unknown):v is "ready"{return typeof v==="string";}'],
      ["contextual closed-domain callback retains its input", 'const check:(v:"ready"|null)=>boolean=(v:unknown):v is "ready"=>typeof v==="string";'],
      ["contextual object promise retains its input", 'const check:(v:object)=>boolean=(v:unknown):v is object=>typeof v==="object";'],
      ["contextual bottom signature is not the public contract", 'const check:(v:number)=>boolean=(v:unknown):v is never=>typeof v==="number";'],
      ["unique symbol is not the broad symbol type", 'declare const marker: unique symbol; function check(v: unknown): v is typeof marker { return typeof v === "symbol"; }'],
      ["mixed literal target still needs richer proof", 'function check(v: unknown): v is string | true { return typeof v === "string"; }'],
      ["brands can intentionally share a primitive runtime carrier", 'type Id = string & { readonly role: unique symbol }; function check(v: unknown): v is Id { return typeof v === "string"; }'],
      ["structural target is intentionally excluded", 'function check(v: unknown): v is { id: string } { return typeof v === "object"; }'],
      ["null-only input is actually recognized by typeof-object", 'function check(v:null):v is null{return typeof v==="object";}'],
      ["generic validator has an opaque target", 'function check<T>(v: unknown): v is T { return typeof v === "number"; }'],
      ["generic input remains opaque", 'function check<T extends string | number>(v: T): v is T & string { return typeof v === "number"; }'],
      ["structural input has unknown runtime possibilities", 'function check(v: { length: number } | string): v is string { return typeof v === "number"; }'],
      ["any input remains under existing unsafe controls", 'function check(v: any): v is string { return typeof v === "number"; }'],
      ["compiler owns impossible predicate target", 'function check(v: number): v is string { return typeof v === "number"; }'],
      ["unnecessary-condition owns impossible comparison", 'function check(v: string): v is string { return typeof v === "number"; }'],
      ["two-sided boolean condition needs its own analysis", 'function check(v: unknown): v is string | number { return typeof v === "string" || typeof v === "number"; }'],
      ["range constraints are outside primitive equality", 'function check(v: unknown): v is number { return typeof v === "number" && v > 0; }'],
      ["multi-statement validator can have other invariants", 'function check(v: unknown): v is string { inspect(v); return typeof v === "number"; }'],
      ["mutation before test is not inspected", 'function check(v: unknown): v is string { v = parse(v); return typeof v === "number"; }'],
      ["helper validators are opaque", 'function check(v: unknown): v is string { return helper(v); }'],
      ["boolean return carries no type predicate promise", 'function check(v: unknown): boolean { return typeof v === "number"; }'],
      ["inferred predicate is compiler-owned", 'const check = (v: unknown) => typeof v === "number";'],
      ["assertion functions have different semantics", 'function check(v: unknown): asserts v is string { if (typeof v !== "string") throw new Error(); }'],
      ["declaration-only predicate has no implementation", 'declare function check(v: unknown): v is string;'],
      ["this predicate has no named parameter", 'class Value { check(): this is this & { ready: true } { return typeof this === "number"; } }'],
      ["different parameter does not establish target relationship", 'function check(v: unknown, other: unknown): v is string { return typeof other === "number"; }'],
      ["destructured parameter is outside direct binding proof", 'function check({ value }: { value: unknown }): value is string { return typeof value === "number"; }'],
      ["property test is not a direct parameter test", 'function check(v: unknown): v is string { return typeof v.value === "number"; }'],
      ["negative comparison has an open complement", 'function check(v: unknown): v is string { return typeof v !== "number"; }'],
      ["dynamic typeof expectation is opaque", 'function check(v: unknown): v is string { return typeof v === expected; }'],
      ["invalid typeof spelling belongs to valid-typeof", 'function check(v: unknown): v is string { return typeof v === "null"; }'],
      ["alias target retains consistent kind", 'type DomainText = string; function check(v: unknown): v is DomainText { return typeof v === "string"; }'],
    ].map(([name, code]) => ({ name, code })),
    { name: "exact-code suppression", code: '// eslint-disable-next-line @rule-tester/no-contradictory-type-predicate -- external declaration compatibility\nfunction check(v: unknown): v is string { return typeof v === "number"; }' },
    { name: "generated ownership", filename: 'guard.generated.ts', code: 'function check(v: unknown): v is string { return typeof v === "number"; }' },
  ],
  invalid: [
    ...["\n", "\r\n", "\r", "\u2028", "\u2029"].map((ending) => ({
      name: "private record predicate retains every annotation terminator " + JSON.stringify(ending),
      code: `export type Kept = Account; type Account = { id: string }; function check(v: unknown): v is${ending}Account { return typeof v === "object"; }`,
      output: `export type Kept = Account; type Account = { id: string }; function check(v: unknown): boolean${ending} { return typeof v === "object"; }`,
      errors: [{ messageId: "uncheckedRecordFields" as const }],
    })),
    { name: "private predicate retains mixed Unicode and CRLF terminators",
      code: "export {}; function check(v: unknown): v is string\u2028|\r\nnumber\u2029 { return typeof v === \"string\"; }",
      output: "export {}; function check(v: unknown): boolean\u2028\r\n\u2029 { return typeof v === \"string\"; }",
      errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "private predicate refuses an internal bare CR and separate LF merge",
      code: "export {}; function check(v: unknown): v is string\r|\nnumber { return typeof v === \"string\"; }",
      output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "private predicate refuses a CR and following source LF boundary merge",
      code: "export {}; function check(v: unknown): v is\rstring\n { return typeof v === \"number\"; }",
      output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "unused private record predicate retains independent exported type use", code: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === \"object\" && v !== null; }", output: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): boolean { return typeof v === \"object\" && v !== null; }", errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "unused private direct object predicate retains runtime check", code: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === \"object\"; }", output: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): boolean { return typeof v === \"object\"; }", errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "record predicate used by caller stays manual", code: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === \"object\" && v !== null; } check({});", output: null, errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "public record predicate stays manual", code: "export type Kept = Account; type Account = { id: string }; export function check(v: unknown): v is Account { return typeof v === \"object\" && v !== null; }", output: null, errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "eval can observe private record contract", code: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === \"object\" && v !== null; } eval(\"check\");", output: null, errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "predicate comment retains custody", code: "export type Kept = Account; type Account = { id: string }; function check(v: unknown): v is /* retain boundary */ Account { return typeof v === \"object\" && v !== null; }", output: null, errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "sole named record use stays live", code: "export {}; type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === \"object\" && v !== null; }", output: null, errors: [{ messageId: "uncheckedRecordFields" }] },
    { name: "record predicate preserves CRLF annotation custody", code: "export type Kept = Account; type Account = { id: string };\r\nfunction check(v: unknown): v is\r\nAccount { return typeof v === \"object\"; }\r\n", output: "export type Kept = Account; type Account = { id: string };\r\nfunction check(v: unknown): boolean\r\n { return typeof v === \"object\"; }\r\n", errors: [{ messageId: "uncheckedRecordFields" }] },
    ...[
      ["named record without fields", 'type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === "object"; }'],
      ["named record with null exclusion", 'type Account = { id: string }; function check(v: unknown): v is Account { return typeof v === "object" && v !== null; }'],
      ["interface with reversed checks", 'interface Account { readonly id: string; } function check(v: unknown): v is Account { return null !== v && "object" === typeof v; }'],
      ["already non-null object is still missing fields", 'type Account = { id: string }; function check(v: object): v is Account { return typeof v === "object"; }'],
    ].map(([name, code]) => ({ name, code, output: null, errors: [{ messageId: "uncheckedRecordFields" as const }] })),
    { name: "preserves the sole named contradictory predicate binding", code: "export {}; type Numeric = number; function check(v: unknown): v is Numeric { return typeof v === \"string\"; }", output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "corrects a contradiction with an independent exported type use", code: "export type Kept = Numeric; type Numeric = number; function check(v: unknown): v is Numeric { return typeof v === \"string\"; }", output: "export type Kept = Numeric; type Numeric = number; function check(v: unknown): boolean { return typeof v === \"string\"; }", errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "corrects an unused private primitive guard", code: "export {}; function check(v:unknown): v is string { return typeof v === \"number\"; }", output: "export {}; function check(v:unknown): boolean { return typeof v === \"number\"; }", errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "corrects an unused private closed-domain guard", code: "export {}; function check(v:unknown): v is \"ready\" { return typeof v === \"string\"; }", output: "export {}; function check(v:unknown): boolean { return typeof v === \"string\"; }", errors: [{ messageId: "closedLiteralPredicate" }] },
    { name: "corrects an unused private array guard", code: "export {}; function check(v:unknown): v is string[] { return Array.isArray(v); }", output: "export {}; function check(v:unknown): boolean { return Array.isArray(v); }", errors: [{ messageId: "uncheckedArrayElements" }] },
    { name: "preserves a consumed guard contract", code: "export {}; function check(v:unknown): v is string { return typeof v === \"number\"; } consume(check);", output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "preserves an exported guard contract", code: "export function check(v:unknown): v is string { return typeof v === \"number\"; }", output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "preserves a dynamic private guard reference", code: "export {}; function check(v:unknown): v is string { return typeof v === \"number\"; } eval(\"check\");", output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "preserves useful predicate comments", code: "export {}; function check(v:unknown): v is /* reviewed boundary */ string { return typeof v === \"number\"; }", output: null, errors: [{ messageId: "contradictoryPredicate" }] },
    { name: "public contradictory predicate", code: NO_CONTRADICTORY_TYPE_PREDICATE_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "contradictoryPredicate" }] },
    ...[
      ["number promised but string checked", 'function check(v: unknown): v is number { return typeof v === "string"; }'],
      ["boolean promised but number checked", 'function check(v: unknown): v is boolean { return typeof v === "number"; }'],
      ["bigint promised but boolean checked", 'function check(v: unknown): v is bigint { return typeof v === "boolean"; }'],
      ["symbol promised but undefined checked", 'function check(v: unknown): v is symbol { return typeof v === "undefined"; }'],
      ["undefined promised but string checked", 'function check(v: unknown): v is undefined { return typeof v === "string"; }'],
      ["object accepted by a primitive promise", 'function check(v: unknown): v is string { return typeof v === "object"; }'],
      ["function accepted by a primitive promise", 'function check(v: unknown): v is string { return typeof v === "function"; }'],
      ["finite primitive input mismatch", 'function check(v: string | number): v is string { return typeof v === "number"; }'],
      ["nullable input mismatch", 'function check(v: string | null): v is string { return typeof v === "object"; }'],
      ["false branch must not exclude rejected numeric alternatives", 'function check(v: string | number | boolean): v is string | number { return typeof v === "string"; }'],
      ["unknown input still promises all target alternatives", 'function check(v: unknown): v is string | number { return typeof v === "string"; }'],
      ["complete boolean constituent is recognized in wider union", 'function check(v: unknown): v is string | boolean { return typeof v === "string"; }'],
      ["loose equality preserves typeof semantics", 'function check(v: unknown): v is string { return typeof v == "number"; }'],
      ["reversed equality operands", 'function check(v: unknown): v is string { return "number" === typeof v; }'],
      ["no-substitution template typeof kind", 'function check(v: unknown): v is string { return typeof v === `number`; }'],
      ["expression-bodied arrow", 'const check = (v: unknown): v is string => typeof v === "number";'],
      ["function expression", 'const check = function(v: unknown): v is string { return typeof v === "number"; };'],
      ["class method", 'class Guard { check(v: unknown): v is string { return typeof v === "number"; } }'],
      ["object method", 'const guard = { check(v: unknown): v is string { return typeof v === "number"; } };'],
      ["alias target is resolved semantically", 'type DomainText = string; function check(v: unknown): v is DomainText { return typeof v === "number"; }'],
      ["same-spelled outer variable cannot steal parameter identity", 'const v = "outer"; function check(v: unknown): v is string { return typeof v === "number"; }'],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "contradictoryPredicate" as const }] })),
    { name: "type predicates in tests retain their promise", filename: 'guard.test.ts', code: 'function check(v: unknown): v is string { return typeof v === "number"; }', errors: [{ messageId: "contradictoryPredicate" }] },
    ...[
      ["primitive-wide string check overclaims a closed literal", 'function check(v:unknown):v is "ready"{return typeof v==="string";}'],
      ["primitive-wide number check overclaims a closed literal", 'function check(v:unknown):v is 42{return typeof v==="number";}'],
      ["primitive-wide boolean check admits false", 'function check(v:unknown):v is true{return typeof v==="boolean";}'],
      ["primitive-wide bigint check overclaims a closed literal", 'function check(v:unknown):v is 1n{return typeof v==="bigint";}'],
      ["closed literal union remains a finite domain", 'function check(v:unknown):v is "ready"|"done"{return typeof v==="string";}'],
      ["broad declared primitive input exceeds closed target", 'function check(v:string|null):v is "ready"{return typeof v==="string";}'],
      ["closed input has an extra admitted literal", 'function check(v:"ready"|"done"|null):v is "ready"{return typeof v==="string";}'],
      ["literal target rejects a member of another runtime kind", 'function check(v:"ready"|1):v is "ready"|1{return typeof v==="string";}'],
      ["null promise admits non-null objects with unknown input", 'function check(v:unknown):v is null{return typeof v==="object";}'],
      ["enum closed target does not cover unknown numbers", 'enum E{One=1,Two=2}function check(v:unknown):v is E{return typeof v==="number";}'],
      ["enum input has an extra admitted member", 'enum E{One=1,Two=2}function check(v:E):v is E.One{return typeof v==="number";}'],
      ["reversed loose literal-domain check", 'function check(v:unknown):v is "ready"{return "string"==typeof v;}'],
    ].map(([name,code])=>({name,code,errors:[{messageId:"closedLiteralPredicate" as const}]})),
    ...[
      ["bottom target cannot admit a number", 'function check(v:unknown):v is never{return typeof v==="number";}'],
      ["bottom target cannot admit a declared literal", 'function check(v:1|2):v is never{return typeof v==="number";}'],
      ["bottom alias is semantically empty", 'type Empty=string&number;function check(v:unknown):v is Empty{return typeof v==="string";}'],
    ].map(([name,code])=>({name,code,errors:[{messageId:"contradictoryPredicate" as const}]})),
    ...[
      ["intrinsic object target excludes accepted null", 'function check(v:unknown):v is object{return typeof v==="object";}'],
      ["nullable input still admits null", 'function check(v:object|null):v is object{return typeof v==="object";}'],
      ["intrinsic object alias preserves null exclusion", 'type Domain=object;function check(v:unknown):v is Domain{return typeof v==="object";}'],
      ["class object method keeps existing analysis", 'class Guard{check(v:unknown):v is object{return typeof v==="object";}}'],
      ["reversed loose intrinsic object check", 'function check(v:unknown):v is object{return "object"==typeof v;}'],
    ].map(([name,code])=>({name,code,errors:[{messageId:"nullAccepted" as const}]})),
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-contradictory-type-predicate without type information", rule, {
  valid: ['function check(v: unknown): v is string { return typeof v === "number"; }'], invalid: [],
});

const POLICY_TESTER = new RuleTester({ languageOptions: { parser } });
POLICY_TESTER.run("no-contradictory-type-predicate null policy", rule, {
  valid: [nullPolicyCase(false)],
  invalid: [{ ...nullPolicyCase(true), errors: [{ messageId: "nullAccepted" }] }],
});

function nullPolicyCase(strictNullChecks: boolean) {
  const code = 'function check(v:unknown):v is object{return typeof v==="object";}';
  const filename = join(import.meta.dirname, "..", "fixtures", "null-policy.ts");
  const options: ts.CompilerOptions = { strict: true, strictNullChecks, noEmit: true, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, code, version, true) : original(path, version, onError, create);
  return { name: strictNullChecks ? "strict policy excludes null" : "loose policy does not prove null exclusion", code, filename, languageOptions: { parserOptions: { programs: [ts.createProgram([filename], options, host)] } } };
}
