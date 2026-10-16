// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import rule from "../../src/rules/no-cors-wildcard-with-credentials.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-cors-wildcard-with-credentials", rule, {
  valid: [
    { name: "keeps wildcard origin with erased false credentials", code: 'import cors from "cors"; cors({origin: `*`, credentials: (false as const)});' },
    { name: "keeps a trusted no-substitution template origin", code: 'cors({origin: `https://app.example.com`, credentials: (true as const)});' },
    { name: "keeps interpolated origins opaque", code: 'cors({origin: `*${suffix}`, credentials: (true as const)});' },
    { name: "keeps unresolved computed CORS option keys opaque", code: 'cors({[originKey]: `*`, credentials: (true as const)});' },
    { name: "does not merge computed headers from different receivers", code: 'first["set"](`Access-Control-Allow-Origin`, `*`); second["set"](`Access-Control-Allow-Credentials`, `true`);' },

    { name: "computed binding keys can mutate after literal initializers", code: "const headers=new Headers();function mutate(){headers.set('Access-Control-Allow-Origin','https://app.example.com');return 'key';}headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');const {[mutate()]:value}=1;" },
    { name: "binding defaults can mutate after literal initializers", code: "const headers=new Headers();function mutate(){headers.set('Access-Control-Allow-Origin','https://app.example.com');return 'value';}headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');const {missing=mutate()}=1;" },
    { name: "interpolated template keys remain unproved", code: "import cors from 'cors';cors({[`or${part}gin`]:'*',credentials:true});" },
    { name: "an alias later overrides the original receiver", code: "const alias=headers;headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');alias.set('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "the original later overrides an alias receiver", code: "const alias=headers;alias.set('Access-Control-Allow-Origin','*');alias.set('Access-Control-Allow-Credentials','true');headers.set('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "a fresh receiver also loses proof when aliased", code: "const headers=new Headers();const alias=headers;headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');alias.set('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "assignment aliases invalidate both bindings", code: "let alias;alias=headers;headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');alias.set('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "the original overrides an assignment alias", code: "let alias;alias=headers;alias.set('Access-Control-Allow-Origin','*');alias.set('Access-Control-Allow-Credentials','true');headers.set('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "erased wrappers preserve visible aliasing", code: "const alias=headers as Headers;headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');alias.set('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "a receiver passed to another function loses proof", code: "register(headers);headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');" },
    { name: "another header value can have a mutating string conversion", code: "const headers={extra:{toString(){headers['Access-Control-Allow-Origin']='https://app.example.com';return 'kept';}},'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'};new Headers(headers);" },
    { name: "trusted imported options", code: "import cors from 'cors';cors({origin:'https://app.example.com',credentials:true});" },
    { name: "credentialless wildcard", code: "import cors from 'cors';cors({origin:'*'});" },
    { name: "credentials disabled", code: "import cors from 'cors';cors({origin:'*',credentials:false});" },
    { name: "unrelated cors function", code: "function cors(value){return value;}cors({origin:'*',credentials:true});" },
    { name: "unproved member and constructor", code: "app.cors({origin:'*',credentials:true});new Cors({origin:'*',credentials:true});" },
    { name: "shadowed official import", code: "import cors from 'cors';function configure(cors){cors({origin:'*',credentials:true});}" },
    { name: "unrelated module import", code: "import cors from './cors.js';cors({origin:'*',credentials:true});" },
    { name: "mutated imported binding", code: "import cors from 'cors';cors=custom;cors({origin:'*',credentials:true});" },
    { name: "unproved local alias", code: "import cors from 'cors';const configure=cors;configure({origin:'*',credentials:true});" },
    { name: "callback star is not a literal option", code: "import cors from 'cors';cors({origin:()=>'*',credentials:true});" },
    { name: "a callback contains an unrelated star", code: "import cors from 'cors';cors({origin(){log('*');return 'https://app.example.com';},credentials:true});" },
    { name: "origin arrays do not imply a wildcard header", code: "import cors from 'cors';cors({origin:['*'],credentials:true});" },
    { name: "conditional origins remain unproved", code: "import cors from 'cors';cors({origin:condition?'https://app.example.com':'*',credentials:true});" },
    { name: "later option replaces origin", code: "import cors from 'cors';cors({origin:'*',credentials:true,...{origin:'https://app.example.com'}});" },
    { name: "later option disables credentials", code: "import cors from 'cors';cors({origin:'*',credentials:true,credentials:false});" },
    { name: "unknown option spread", code: "import cors from 'cors';cors({origin:'*',credentials:true,...options});" },
    { name: "option getter", code: "import cors from 'cors';cors({origin:'*',credentials:true,get methods(){return configure();}});" },
    { name: "unknown computed option", code: "import cors from 'cors';cors({origin:'*',credentials:true,[key]:value});" },
    { name: "header credentials value is case sensitive", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'TRUE'};" },
    { name: "non HTTP whitespace", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true\\u00a0'};" },
    { name: "trusted header origin", code: "const headers={'Access-Control-Allow-Origin':'https://app.example.com','Access-Control-Allow-Credentials':'true'};" },
    { name: "credentialless header map", code: "const headers={'Access-Control-Allow-Origin':'*'};" },
    { name: "last identical property wins", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true','Access-Control-Allow-Origin':'https://app.example.com'};" },
    { name: "literal spread is later overridden", code: "const headers={...{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'},'Access-Control-Allow-Origin':'https://app.example.com'};" },
    { name: "conditional spread source is later overridden", code: "const headers={...(condition?{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'}:{}),'Access-Control-Allow-Origin':'https://app.example.com'};" },
    { name: "unknown spread can replace headers", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true',...other};" },
    { name: "unknown computed key can replace headers", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true',[key]:value};" },
    { name: "header getter", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true',get extra(){return mutate();}};" },
    { name: "unknown header prototype", code: "const headers={__proto__:prototype,'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'};" },
    { name: "differently-cased origins are combined", code: "new Headers({'Access-Control-Allow-Origin':'*','access-control-allow-origin':'https://app.example.com','Access-Control-Allow-Credentials':'true'});" },
    { name: "differently-cased credentials are combined", code: "new Headers({'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true','access-control-allow-credentials':'true'});" },
    { name: "later setter resets origin", code: "res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Credentials','true');res.setHeader('Access-Control-Allow-Origin','https://app.example.com');" },
    { name: "later setter disables credentials", code: "headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');headers.set('Access-Control-Allow-Credentials','false');" },
    { name: "delete removes origin", code: "headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');headers.delete('Access-Control-Allow-Origin');" },
    { name: "removeHeader removes credentials", code: "res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Credentials','true');res.removeHeader('Access-Control-Allow-Credentials');" },
    { name: "different response bindings", code: "first.setHeader('Access-Control-Allow-Origin','*');second.setHeader('Access-Control-Allow-Credentials','true');" },
    { name: "different functions", code: "function first(){res.setHeader('Access-Control-Allow-Origin','*');}function second(){res.setHeader('Access-Control-Allow-Credentials','true');}" },
    { name: "exclusive branches", code: "function configure(res,condition){if(condition)res.setHeader('Access-Control-Allow-Origin','*');else res.setHeader('Access-Control-Allow-Credentials','true');}" },
    { name: "later branch may replace headers", code: "function configure(res,condition){res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Credentials','true');if(condition)res.setHeader('Access-Control-Allow-Origin','https://app.example.com');}" },
    { name: "nested block is not a final state", code: "function configure(res){{res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Credentials','true');}res.setHeader('Access-Control-Allow-Origin','https://app.example.com');}" },
    { name: "unknown call may mutate headers", code: "headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');configure(headers);" },
    { name: "dynamic setter value loses proof", code: "headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');headers.set('Access-Control-Allow-Origin',origin);" },
    { name: "reassignment replaces receiver", code: "let headers;headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');headers=new Headers();" },
    { name: "member getter returns different receivers", code: "const response={get headers(){return new Headers();}};response.headers.set('Access-Control-Allow-Origin','*');response.headers.set('Access-Control-Allow-Credentials','true');" },
    { name: "unknown initial append value", code: "headers.append('Access-Control-Allow-Origin','*');headers.append('Access-Control-Allow-Credentials','true');" },
    { name: "append combines values", code: "const headers=new Headers();headers.append('Access-Control-Allow-Origin','https://app.example.com');headers.append('Access-Control-Allow-Origin','*');headers.append('Access-Control-Allow-Credentials','true');" },
    { name: "shadowed Headers constructor", code: "function configure(Headers){const headers=new Headers();headers.append('Access-Control-Allow-Origin','*');headers.append('Access-Control-Allow-Credentials','true');}" },
    { name: "manual credentials are case sensitive", code: "res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Credentials','True');" },
    { name: "optional setter may not execute", code: "headers.set?.('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');" },
  ],
  invalid: [
    { name: "retains a wildcard no-substitution template origin", code: 'import cors from "cors"; cors({origin: `*`, credentials: true});', errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "retains wildcard and credential literals through const assertions", code: 'import cors from "cors"; cors({origin: ("*" as const), credentials: (true as const)});', errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "recognizes static computed CORS option names", code: 'import cors from "cors"; cors({["origin"]: `*`, ["credentials"]: (true as const)});', errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "retains static computed header pairs with template arguments", code: 'res["set"](`Access-Control-Allow-Origin`, `*`); res["set"](`Access-Control-Allow-Credentials`, `true`);', errors: [{ messageId: "corsWildcardWithCredentials" }] },

    { name: "static cooked template option keys", code: "import cors from 'cors';cors({[`or\\u0069gin`]:'*',[`credentials`]:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "erased type queries do not escape a receiver", code: "const headers=new Headers();type Bag=typeof headers;type Setter=typeof headers.set;headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "an inert null prototype", code: "const headers={__proto__:null,'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'};", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "official cors options", code: "import cors from 'cors';cors({origin:'*',credentials:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "renamed official import", code: "import configure from 'cors';configure({origin:'*',credentials:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "named default import", code: "import {default as configure} from 'cors';configure({origin:'*',credentials:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "official Hono alias", code: "import {cors as configure} from 'hono/cors';configure({origin:'*',credentials:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "official Hono namespace", code: "import * as middleware from 'hono/cors';middleware.cors({origin:'*',credentials:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "effective literal option writes", code: "import cors from 'cors';cors({origin:'https://app.example.com',...{origin:'*'},credentials:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "computed literal option keys", code: "import cors from 'cors';cors({['origin']:'*',['credentials']:true});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "literal header map", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'};", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "case insensitive header names", code: "const headers={'access-control-allow-origin':'*','ACCESS-CONTROL-ALLOW-CREDENTIALS':'true'};", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "outer literal spread is reported once", code: "const headers={...{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'}};", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "Response header map", code: "new Response(body,{headers:{'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':'true'}});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "native HTTP whitespace is trimmed", code: "new Headers({'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':' \\ttrue\\r\\n'});", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "boolean has native string conversion", code: "const headers={'Access-Control-Allow-Origin':'*','Access-Control-Allow-Credentials':true};", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "same identifier setHeader", code: "res.setHeader('Access-Control-Allow-Origin','*');res.setHeader('Access-Control-Allow-Credentials','true');", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "straight line function body", code: "function configure(headers){headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');}", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "later setter reintroduces wildcard", code: "headers.set('Access-Control-Allow-Origin','https://app.example.com');headers.set('Access-Control-Allow-Origin','*');headers.set('Access-Control-Allow-Credentials','true');", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "fresh native Headers append", code: "const headers=new Headers();headers.append('Access-Control-Allow-Origin','*');headers.append('Access-Control-Allow-Credentials','true');", errors: [{ messageId: "corsWildcardWithCredentials" }] },
    { name: "known removals before append", code: "headers.delete('Access-Control-Allow-Origin');headers.delete('Access-Control-Allow-Credentials');headers.append('Access-Control-Allow-Origin','*');headers.append('Access-Control-Allow-Credentials','true');", errors: [{ messageId: "corsWildcardWithCredentials" }] },
  ],
});

describe("native CORS header behavior", () => {
  it("combines differently-cased keys after exact JavaScript key overrides", () => {
    const headers = new Headers({
      "Access-Control-Allow-Origin": "*",
      ...{ "Access-Control-Allow-Origin": "https://app.example.com" },
      "access-control-allow-origin": "*",
    });
    expect(headers.get("access-control-allow-origin")).toBe("https://app.example.com, *");
  });

  it("trims HTTP whitespace while preserving credentials value case", () => {
    const headers = new Headers({ "Access-Control-Allow-Credentials": " \tTrue\r\n" });
    expect(headers.get("access-control-allow-credentials")).toBe("True");
  });
});
