import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import ts from "typescript";
import { afterAll, describe, it } from "vitest";

import rule, { NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION } from "../../src/rules/no-contradictory-overload-return.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });
const GOOD = NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION.examples[0].files[0].source;
const BAD = NO_CONTRADICTORY_OVERLOAD_RETURN_DOCUMENTATION.examples[1].files[0].source;
const SCALAR = 'function choose(kind:"a"):1;function choose(kind:"b"):2;function choose(kind:"a"|"b"):number{return kind==="a"?2:1;}';
const ERRORS = [{ messageId: "contradictoryReturn" }, { messageId: "contradictoryReturn" }] as const;

TESTER.run("no-contradictory-overload-return", rule, {
  valid: [
    { name: "public correct case map", code: GOOD },
    ...[
      ["broad implementation annotation does not widen actual literal evidence", GOOD.replace('{kind: "text" | "count"}', '{kind:string}')],
      ["correct scalar relationship", SCALAR.replace('?2:1', '?1:2')],
      ["only explicit present values are proven", BAD.replace('{kind: "count"} : {kind: "text"}', '{} : {}').replace('{kind: "text" | "count"}', '{}')],
      ["broad public input can mask a specific overload", BAD.replace('function load(kind: "text")', 'function load(kind: string)')],
      ["aliased public input stays opaque", 'type Text="text";'+BAD.replace('kind: "text")', 'kind: Text)')],
      ["duplicate public input can mask a later signature", BAD.replace('function load(kind: "count")', 'function load(kind: "text")')],
      ["signed zero overloads collide under strict equality", 'function z(v:0):1;function z(v:-0):2;function z(v:number):number{return v===0?2:1;}'],
      ["equivalent numeric spellings collide", 'function z(v:1):1;function z(v:1.0):2;function z(v:number):number{return v===1?2:1;}'],
      ["single public overload is outside the admitted relationship", BAD.replace('function load(kind: "count"): {kind: "count"};\n', '')],
      ["multi input contracts need independent relation analysis", BAD.replaceAll('kind:', 'other:number,kind:')],
      ["optional public argument", BAD.replace('load(kind: "text")', 'load(kind?: "text")')],
      ["optional implementation argument", BAD.replace('load(kind: "text" | "count")', 'load(kind?: "text" | "count")')],
      ["implementation default may run effects", BAD.replace('load(kind: "text" | "count")', 'load(kind: "text" | "count" = sideEffect())')],
      ["generic callable contract", BAD.replaceAll('function load(', 'function load<T>(')],
      ["additional statements are not a sole return", BAD.replace('{ return kind', '{ sideEffect(); return kind')],
      ["loose equality has independent coercion semantics", BAD.replace('===', '==')],
      ["computed comparison is not a literal", BAD.replace('=== "text"', '=== resolveKind()')],
      ["asserted return is owned by existing assertion rules", BAD.replace('{kind: "count"} : {kind: "text"}', '({kind: "count"} as const) : ({kind: "text"} as const)')],
      ["calls in a branch may throw before a result exists", BAD.replace('{kind: "count"} :', '{kind: "count",extra:sideEffect()} :')],
      ["getters are not pure property values", BAD.replace('{kind: "count"} :', '{get kind(){return "count";}} :')],
      ["spreads may replace the observed property", BAD.replace('{kind: "count"} :', '{kind: "count",...extension} :')],
      ["computed keys may replace the observed property", BAD.replace('{kind: "count"} :', '{[key]: "count"} :')],
      ["duplicate identifier and quoted keys", BAD.replace('{kind: "count"} :', '{kind:"count","kind":"text"} :')],
      ["duplicate numeric spellings", BAD.replace('{kind: "count"} :', '{kind:"count",1:0,"1":1} :')],
      ["prototype semantics are outside flat records", BAD.replace('{kind: "count"} :', '{kind:"count",__proto__:null} :')],
      ["branded property contracts need independent runtime evidence", 'type Brand=string&{readonly role:unique symbol};'+BAD.replace('{kind: "text"}', '{kind:Brand}').replace('{kind: "count"}', '{kind:Brand}')],
      ["enum property membership stays with its domain authority", 'enum E{Text="text",Count="count"}'+BAD.replaceAll('{kind: "text"}', '{kind:E.Text}').replaceAll('{kind: "count"}', '{kind:E.Count}')],
      ["compiler invalid input envelope", BAD.replace('kind: "text" | "count"', 'kind: number')],
      ["compiler invalid output envelope", BAD.replace('{kind: "text" | "count"}', 'number')],
      ["void callback result does not promise undefined", 'function f(v:0):void;function f(v:1):void;function f(v:number):void{return v===0?undefined:undefined;}'],
      ["namespace declarations have a separate owner", 'namespace Owner{'+BAD+'}'],
      ["generated contracts preserve their owner", '// @generated\n'+BAD],
    ].map(([name,code])=>({name,code})),
    { name: "generated path", filename: "overloads.generated.ts", code: BAD },
    { name: "exact suppression", code: BAD.replace('return kind', '// eslint-disable-next-line @rule-tester/no-contradictory-overload-return -- compatibility contract separately reviewed\nreturn kind') },
  ],
  invalid: [
    { name: "public inverted variants", code: BAD, errors: ERRORS },
    { name: "scalar results retain their relation", code: SCALAR, errors: ERRORS },
    { name: "literal record value despite broad implementation type", code: BAD.replace('{kind: "text" | "count"}', '{kind:string}'), errors: ERRORS },
    { name: "strict inequality selects opposite branch", code: GOOD.replace('===', '!=='), errors: ERRORS },
    { name: "reversed strict literal comparison", code: BAD.replace('kind === "text"', '"text" === kind'), errors: ERRORS },
    { name: "parenthesized actual comparison", code: BAD.replace('kind === "text"', '((kind) === ("text"))'), errors: ERRORS },
    { name: "public exported function", code: BAD.replaceAll('function load', 'export function load'), errors: ERRORS },
    { name: "tests retain actual result contracts", filename: "overloads.test.ts", code: BAD, errors: ERRORS },
    { name: "boolean inputs select concrete literal outputs", code: 'function f(v:true):1;function f(v:false):2;function f(v:boolean):number{return v===true?2:1;}', errors: ERRORS },
    { name: "negative numeric inputs select concrete outputs", code: 'function f(v:-1):"negative";function f(v:1):"positive";function f(v:number):string{return v===-1?"positive":"negative";}', errors: ERRORS },
    { name: "null input is distinct from string input", code: 'function f(v:null):0;function f(v:"a"):1;function f(v:null|string):number{return v===null?1:0;}', errors: ERRORS },
    { name: "one bad branch shared by several inputs is deduplicated", code: 'function f(v:"a"):1;function f(v:"b"):2;function f(v:"c"):2;function f(v:string):number{return v==="a"?1:0;}', errors: [{messageId:"contradictoryReturn"}] },
    { name: "numeric record key uses its canonical property", code: 'function f(v:0):{1:1};function f(v:1):{"1":2};function f(v:number):{1:number}{return v===0?{"1":2}:{1:1};}', errors: ERRORS },
    { name: "extra domain fields do not hide explicit contradicting values", code: BAD.replace('{kind: "text" | "count"}', '{kind: "text" | "count",other?:number}').replace('{kind: "count"} : {kind: "text"}', '{kind:"count",other:1} : {kind:"text",other:2}'), errors: ERRORS },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-contradictory-overload-return without a program", rule, { valid: [BAD], invalid: [] });

const POLICY_TESTER = new RuleTester({ languageOptions: { parser } });
const NULL_OVERLOAD = 'function f(v:"a"):1;function f(v:null):2;function f(v:"a"|null):number{return v==="a"?1:1;}';
POLICY_TESTER.run("no-contradictory-overload-return null overload reachability", rule, {
  valid: [policyCase("loose null allows an earlier overload to mask the null signature", NULL_OVERLOAD, false)],
  invalid: [
    { ...policyCase("strict null exposes the actual null case promise", NULL_OVERLOAD, true), errors: [{ messageId: "contradictoryReturn" }] },
    { ...policyCase("distinct non-null cases remain reachable under loose null policy", SCALAR, false), errors: ERRORS },
  ],
});

function policyCase(name: string, code: string, strictNullChecks: boolean) {
  const filename = join(import.meta.dirname, "..", "fixtures", "overload-null-policy.ts");
  const options: ts.CompilerOptions = { strict: true, strictNullChecks, noEmit: true, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, code, version, true) : original(path, version, onError, create);
  return { name, code, filename, languageOptions: { parserOptions: { programs: [ts.createProgram([filename], options, host)] } } };
}
