import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION } from "../../src/rules/no-invalid-zod-custom-parse.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });
const IMPORT = 'import {z} from "zod";';

TESTER.run("no-invalid-zod-custom-parse", rule, {
  valid: [
    { name: "public real validator", code: NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION.examples[0].files[0].source },
    ...[
      ["honest unknown accepts any input", 'z.custom<unknown>().parse(1);'],
      ["any is left to the existing unsafe owners", 'z.custom<any>().parse(1);'],
      ["compatible string", 'z.custom<string>().parse("ok");'],
      ["compatible numeric literal", 'z.custom<1>().parse(1);'],
      ["compatible bigint literal", 'z.custom<-1n>().parse(-1n);'],
      ["compatible boolean", 'z.custom<boolean>().parse(false);'],
      ["compatible null", 'z.custom<null>().parse(null);'],
      ["nullable primitive", 'z.custom<string|null>().parse(null);'],
      ["compatible mixed literal domain", 'z.custom<"ready"|42>().parse(42);'],
      ["broad primitive union", 'z.custom<string|number>().parse(1);'],
      ["object-valued targets are excluded", 'z.custom<{id:string}>().parse(1);'],
      ["void contract does not promise an observable primitive", 'z.custom<void>().parse(1);'],
      ["branded backing value is not runtime disjoint", 'type Id=string&{readonly role:unique symbol};z.custom<Id>().parse("ok");'],
      ["intersection target has independent constraints", 'z.custom<string&{length:3}>().parse("ok");'],
      ["string enum has a valid raw backing value", 'enum E{Ready="ready"}z.custom<E>().parse("ready");'],
      ["numeric enum stays outside structural value proof", 'enum E{One=1}z.custom<E>().parse(2);'],
      ["generic target remains opaque", 'function parse<T>(){return z.custom<T>().parse(1);}'],
      ["conditional target remains opaque", 'function parse<T>(){return z.custom<T extends string?string:number>().parse(1);}'],
      ["explicit validator owns validation", 'z.custom<string>(value=>typeof value==="string").parse(1);'],
      ["explicit undefined validator is not an admitted call shape", 'z.custom<string>(undefined).parse(1);'],
      ["complete pipeline owns validation", 'z.custom<string>().pipe(z.string()).parse(1);'],
      ["complete refinement owns validation", 'z.custom<string>().refine(value=>typeof value==="string").parse(1);'],
      ["safeParse is not a direct parsed value", 'z.custom<string>().safeParse(1);'],
      ["schema bindings require independent flow proof", 'const schema=z.custom<string>();schema.parse(1);'],
      ["schema factory alone does not prove a bad parsed value", 'z.custom<string>();'],
      ["dynamic input may actually belong to the target", 'declare const input:unknown;z.custom<string>().parse(input);'],
      ["object input is not a primitive literal", 'z.custom<string>().parse({id:1});'],
      ["parse options leave the minimal admitted shape", 'z.custom<string>().parse(1,{});'],
      ["call aliases are not direct parse calls", 'z.custom<string>().parse.call(undefined,1);'],
      ["namespace replacement invalidates API identity", 'z.custom=customAdapter;z.custom<string>().parse(1);'],
      ["namespace escape invalidates API identity", 'configure(z);z.custom<string>().parse(1);'],
      ["namespace alias invalidates API identity", 'const alias=z;alias.custom=customAdapter;z.custom<string>().parse(1);'],
      ["other namespace APIs conservatively disable proof", 'z.string();z.custom<string>().parse(1);'],
    ].map(([name,code])=>({name,code:IMPORT+code})),
    { name: "shadowed parameter is not the imported namespace", code: IMPORT+'function parse(z:{custom<T>():{parse(value:unknown):T}}){return z.custom<string>().parse(1);}' },
    { name: "shadowed named import is not the native factory", code: 'import {custom} from "zod";function parse(custom:<T>()=>{parse(value:unknown):T}){return custom<string>().parse(1);}' },
    { name: "type-only import is not a runtime factory", code: 'import type {z} from "zod";z.custom<string>().parse(1);' },
    { name: "unrelated module is not Zod", code: 'import {z} from "other";z.custom<string>().parse(1);' },
    { name: "named factory escape invalidates API identity", code: 'import {custom} from "zod";const alias=custom;custom<string>().parse(1);' },
    { name: "named factory mutation invalidates API identity", code: 'import {custom} from "zod";custom=adapter;custom<string>().parse(1);' },
    { name: "exported native capability can escape", code: IMPORT+'export {z};z.custom<string>().parse(1);' },
    { name: "generated sources retain their owner", filename: "custom.generated.ts", code: IMPORT+'z.custom<string>().parse(1);' },
    { name: "exact suppression", code: IMPORT+'\n// eslint-disable-next-line @rule-tester/no-invalid-zod-custom-parse -- externally validated wire carrier\nz.custom<string>().parse(1);' },
  ],
  invalid: [
    { name: "public unchecked incompatible parse", code: NO_INVALID_ZOD_CUSTOM_PARSE_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "incompatibleCustomParse" }] },
    ...[
      ["wrong number carrier", 'z.custom<number>().parse("bad");'],
      ["wrong boolean carrier", 'z.custom<boolean>().parse(0);'],
      ["wrong bigint carrier", 'z.custom<bigint>().parse(1);'],
      ["wrong closed string member", 'z.custom<"ready">().parse("done");'],
      ["wrong closed numeric member", 'z.custom<1>().parse(2);'],
      ["wrong closed bigint member", 'z.custom<1n>().parse(2n);'],
      ["wrong boolean member", 'z.custom<false>().parse(true);'],
      ["wrong null member", 'z.custom<null>().parse(false);'],
      ["wrong undefined member", 'z.custom<undefined>().parse(null);'],
      ["never has no value-space member", 'z.custom<never>().parse(1);'],
      ["outside mixed literal union", 'z.custom<"ready"|42>().parse("done");'],
      ["outside broad primitive union", 'z.custom<string|number>().parse(true);'],
      ["null is outside strict string domain", 'z.custom<string>().parse(null);'],
      ["negative numeric literal", 'z.custom<string>().parse(-1);'],
      ["positive numeric literal", 'z.custom<string>().parse(+1);'],
      ["negative bigint literal", 'z.custom<string>().parse(-1n);'],
      ["computed static API names", 'z["custom"]<string>()["parse"](1);'],
    ].map(([name,code])=>({name,code:IMPORT+code,errors:[{messageId:"incompatibleCustomParse" as const}]})),
    ...[
      ["imported namespace alias", 'import {z as schema} from "zod";schema.custom<string>().parse(1);'],
      ["native namespace import", 'import * as schema from "zod";schema.custom<string>().parse(1);'],
      ["native default import", 'import schema from "zod";schema.custom<string>().parse(1);'],
      ["native named factory alias", 'import {custom as unchecked} from "zod";unchecked<string>().parse(1);'],
      ["native v4 surface", 'import {z} from "zod/v4";z.custom<string>().parse(1);'],
    ].map(([name,code])=>({name,code,errors:[{messageId:"incompatibleCustomParse" as const}]})),
    { name: "real contracts inside tests stay checked", filename: "custom.test.ts", code: IMPORT+'z.custom<string>().parse(1);', errors: [{ messageId: "incompatibleCustomParse" }] },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-invalid-zod-custom-parse without a program", rule, {
  valid: [IMPORT+'z.custom<string>().parse(1);'], invalid: [],
});
