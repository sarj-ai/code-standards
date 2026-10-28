import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";
import { z } from "zod";

import rule, { NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION } from "../../src/rules/no-partial-type-predicate.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });

function predicate(expression: string, target = "number", input = "unknown"): string {
  return `function check(value: ${input}): value is ${target} { return ${expression}; }`;
}

function uuidPredicate(schema = "z.uuid()", expression = "UuidSchema.safeParse(value).success", prefix = 'import { z } from "zod";'): string {
  return `${prefix} const UuidSchema=${schema}; export function check(value:unknown):value is string{return ${expression};}`;
}

TESTER.run("no-partial-type-predicate", rule, {
  valid: [
    {
      name: "local paths alias has its own schema semantics",
      filename: "guard.ts",
      code: 'import {z} from "zod";const Schema=z.uuid();export function isString(value:unknown):value is string{return Schema.safeParse(value).success;}',
      languageOptions: { parserOptions: {
        projectService: false,
        project: join(import.meta.dirname, "..", "fixtures", "uuid-local-module", "tsconfig.json"),
        tsconfigRootDir: join(import.meta.dirname, "..", "fixtures", "uuid-local-module"),
      } },
    },
    { name: "public boolean filter", code: NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION.examples[0].files[0].source },
    ...[
      ["total primitive boundary", predicate('typeof value === "number"')],
      ["total string length", predicate('typeof value === "string" && value.length >= 0', "string")],
      ["total lower length", predicate('typeof value === "string" && value.length > -1', "string")],
      ["direct total length", predicate("value.length >= 0", "string", "string")],
      ["total nullish exclusion", predicate('typeof value === "string" && value !== null', "string")],
      ["ordinary boolean filter", 'function check(value: number): boolean { return value > 0; }'],
      ["inference remains compiler owned", 'function check(value: unknown) { return typeof value === "number" && value > 0; }'],
      ["literal target is a genuine refinement", 'function check(value: string): value is "ready" { return value === "ready"; }'],
      ["boolean literal target is genuine refinement", 'function check(value: boolean): value is true { return value; }'],
      ["branded refinement", 'type Positive = number & { readonly positive: unique symbol }; function check(value: number): value is Positive { return value > 0; }'],
      ["object truthiness is total over the target", 'function check(value: {id: string} | null): value is {id: string} { return !!value; }'],
      ["nonempty tuple has separate domain meaning", 'function check(value: string[]): value is [string, ...string[]] { return value.length > 0; }'],
      ["opaque alias is not inferred", 'function check(value: unknown): value is Domain { return !!value; }'],
      ["union target needs a richer proof", predicate('typeof value === "number" && value > 0', "number | string")],
      ["unknown input numeric comparison is compiler invalid", predicate("value > 0")],
      ["wrong target input relation belongs to compiler", predicate('typeof value === "number" && value > 0', "number", "string")],
      ["any input is already unsafe", predicate('typeof value === "number" && value > 0', "number", "any")],
      ["never input has no witness", predicate("!!value", "number", "never")],
      ["generic predicate target", 'function check<T>(value: T): value is T { return !!value; }'],
      ["numeric enum input excludes the apparent counterexample", 'enum Positive { One=1, Two=2 } function check(value: Positive): value is number { return value > 0; }'],
      ["positive enum truthiness is total over its input", 'enum Positive { One=1, Two=2 } function check(value: Positive | null): value is number { return !!value; }'],
      ["restricted enum does not admit the NaN counterexample", 'enum Positive { One=1, Two=2 } function check(value: Positive): value is number { return value <= 1e309; }'],
      ["constrained generic contract", 'function check<T extends number>(value: T): value is T { return value > 0; }'],
      ["assertion contract is one sided", 'function check(value: number): asserts value is number { if (value <= 0) throw new Error(); }'],
      ["overload exposes only positive literals", 'function check(value: 1 | 2 | string): value is 1 | 2; function check(value: number | string): value is number { return typeof value === "number" && value > 0; }'],
      ["contextual callback protects a narrower domain", 'declare function accept(check: (value: 1 | 2) => boolean): void; accept((value: number): value is number => value > 0);'],
      ["explicit variable callback contract", 'const check: (value: 1 | 2) => boolean = (value: number): value is number => value > 0;'],
      ["function expression contextual contract", 'const check: (value: 1 | 2) => boolean = function(value: number): value is number { return value > 0; };'],
      ["dynamic bound is not inferred", predicate('typeof value === "number" && value > threshold')],
      ["arithmetic is outside the proof", predicate('typeof value === "number" && value * 2 > 0')],
      ["method semantics may be replaced", predicate('typeof value === "string" && value.startsWith("ok")', "string")],
      ["Boolean namespace identity is not inferred", predicate("Boolean(value)")],
      ["wrong parameter is not a witness", predicate('typeof other === "number" && other > 0')],
      ["different check parameter", predicate('typeof value === "number" && other > 0')],
      ["mismatched typeof remains separate", predicate('typeof value === "string" && value.length > 0')],
      ["nested boolean conditions are not inferred", predicate('typeof value === "number" && value > 0 && value < 10')],
      ["or expression has other successful alternatives", predicate('typeof value === "number" || fallback(value)')],
      ["multistatement validator is opaque", 'function check(value: unknown): value is number { validate(value); return !!value; }'],
      ["multiple parameters preserve callback contracts", 'function check(value: number, index: number): value is number { return value > 0; }'],
      ["default input is outside direct binding", 'function check(value: number = 1): value is number { return value > 0; }'],
      ["rest parameter is not a primitive", 'function check(...value: number[]): value is number[] { return value.length > 0; }'],
      ["declaration only", 'declare function check(value: unknown): value is number;'],
      ["ambient library contract has no implementation", 'declare module "boundary" { export function isText(value: unknown): value is string; }'],
      ["this based state contract", 'class Slot { value: string | undefined; hasValue(): this is this & { value: string } { return this.value !== undefined; } }'],
      ["aliased discriminant correlation", 'type State = {kind:"ready";value:string}|{kind:"idle"}; function check(value:State):value is Extract<State,{kind:"ready"}>{const {kind}=value;return kind==="ready";}'],
      ["typed array boundary already establishes its elements", 'function check(value: string[] | null): value is string[] { return Array.isArray(value); }'],
      ["constructor authority needs a separate analysis", 'function check(value: unknown): value is Date { return value instanceof Date; }'],
      ["schema boundary adapter", 'import {z} from "zod"; const TextSchema = z.string(); function check(value: unknown): value is string { return TextSchema.safeParse(value).success; }'],
      ["length witness bound is explicit", predicate('typeof value === "string" && value.length < 1000000000000', "string")],
      ["member predicate is outside direct primitive contract", 'class Check { isValid(): this is this { return !!this; } }'],
      ["method may implement an authoritative port", 'class Check { isValid(value: number): value is number { return value > 0; } }'],
      ["async invalid predicate stays compiler owned", 'async function check(value: unknown): value is number { return !!value; }'],
      ["generator stays excluded", 'function* check(value: unknown): value is number { return !!value; }'],
      ["unchecked cast target is not broadened", 'function check(value: unknown): value is object { return !!value; }'],
    ].map(([name, code]) => ({ name, code })),
    { name: "generated file", filename: "guard.generated.ts", code: predicate('typeof value === "number" && value > 0') },
    { name: "exact suppression", code: `// eslint-disable-next-line @rule-tester/no-partial-type-predicate -- legacy callback contract is reviewed\n${predicate('typeof value === "number" && value > 0')}` },
    ...[
      ["UUID boolean example", NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION.examples[3].files[0].source],
      ["UUID branded domain", 'import {z} from "zod";const UuidSchema=z.uuid().brand<"Uuid">();type Uuid=z.infer<typeof UuidSchema>;export function check(value:unknown):value is Uuid{return UuidSchema.safeParse(value).success;}'],
      ["UUID transform remains opaque", uuidPredicate('z.uuid().transform(value=>value)')],
      ["UUID refine remains opaque", uuidPredicate('z.uuid().refine(value=>value.length>0)')],
      ["UUID default remains opaque", uuidPredicate('z.uuid().default("00000000-0000-4000-8000-000000000000")')],
      ["UUID coercion remains opaque", uuidPredicate('z.coerce.string().uuid()')],
      ["imported schema remains opaque", 'import {UuidSchema} from "./schema.js";export function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}'],
      ["unrelated zod-like module", uuidPredicate('z.uuid()', undefined, 'import {z} from "custom-schema";')],
      ["shadowed zod namespace", 'import {z} from "zod";function create(z:CustomFactory){const UuidSchema=z.uuid();return (value:unknown):value is string=>UuidSchema.safeParse(value).success;}'],
      ["shadowed schema receiver", 'import {z} from "zod";const UuidSchema=z.uuid();function create(UuidSchema:CustomSchema){return (value:unknown):value is string=>UuidSchema.safeParse(value).success;}'],
      ["shadowed parsed parameter", 'import {z} from "zod";const UuidSchema=z.uuid();const other="ready";export function check(value:unknown):value is string{return UuidSchema.safeParse(other).success;}'],
      ["negated parse result", uuidPredicate(undefined, '!UuidSchema.safeParse(value).success')],
      ["asynchronous parse method", uuidPredicate(undefined, 'UuidSchema.safeParseAsync(value).success')],
      ["dynamic success field", uuidPredicate(undefined, 'UuidSchema.safeParse(value)[field]')],
      ["parse method receives options", uuidPredicate(undefined, 'UuidSchema.safeParse(value,options).success')],
      ["other parse options can expose mutable schema internals", uuidPredicate()+'UuidSchema.safeParse("bad",{error:issue=>{(issue.inst as any)._zod.def.pattern.test=()=>true;return "Bad";}}).error;'],
      ["spread parse options can expose mutable schema internals", uuidPredicate()+'UuidSchema.safeParse(...["bad",{error:(issue:any)=>{issue.inst._zod.def.pattern.test=()=>true;return "Bad";}}] as const).error;'],
      ["other parse options are conservatively opaque", uuidPredicate()+'UuidSchema.safeParse("bad",{}).error;'],
      ["parse result alias remains opaque", 'import {z} from "zod";const UuidSchema=z.uuid();export function check(value:unknown):value is string{const result=UuidSchema.safeParse(value);return result.success;}'],
      ["schema alias escapes", uuidPredicate()+ 'const alias=UuidSchema;alias.safeParse=acceptAll;'],
      ["schema method mutation", uuidPredicate()+'UuidSchema.safeParse=acceptAll;'],
      ["schema unknown consumer", uuidPredicate()+'configure(UuidSchema);'],
      ["namespace factory mutation", uuidPredicate()+'z.uuid=customFactory;'],
      ["namespace escape", uuidPredicate()+'configure(z);'],
      ["other namespace value use lacks closed prototype proof", uuidPredicate()+'const other=z.string();'],
      ["reflective mutation", uuidPredicate()+'eval("UuidSchema.safeParse = acceptAll");'],
      ["RegExp prototype can change UUID validation", uuidPredicate()+ 'RegExp.prototype.test=()=>true;'],
      ["reflective RegExp prototype replacement", uuidPredicate()+ 'Object.defineProperty(RegExp.prototype,"test",{value:()=>true});'],
      ["regex prototype capability through literal", uuidPredicate()+ 'Object.getPrototypeOf(/./).test=()=>true;'],
      ["ambient RegExp replacement", uuidPredicate()+ 'globalThis.RegExp=CustomRegExp;'],
      ["regex constructor escape", uuidPredicate()+ 'configure(RegExp);'],
      ["Function constructor invalidates closed proof", uuidPredicate()+ 'Function("RegExp.prototype.test = () => true")();'],
      ["explicit callback contract", 'import {z} from "zod";const UuidSchema=z.uuid();const check:(value:unknown)=>boolean=(value:unknown):value is string=>UuidSchema.safeParse(value).success;'],
      ["UUID schema cast cannot invent an official factory", uuidPredicate('customSchema as z.ZodUUID')],
      ["UUID format factory options remain opaque", uuidPredicate('z.uuid({error:"Public"})')],
    ].map(([name, code])=>({name,code})),
  ],
  invalid: [
    ...[
      ["UUID partial predicate example", NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION.examples[2].files[0].source],
      ["UUID legacy string chain", uuidPredicate('z.string().uuid()')],
      ["UUID ordinary one-argument parse read preserves native behavior", uuidPredicate()+'UuidSchema.safeParse("bad").error;'],
      ["UUID import alias", uuidPredicate('schema.uuid()', undefined, 'import {z as schema} from "zod";')],
      ["UUID namespace import", uuidPredicate('z.uuid()', undefined, 'import * as z from "zod";')],
      ["UUID v4 entry point", uuidPredicate('z.uuid()', undefined, 'import {z} from "zod/v4";')],
      ["UUID v3 string format", uuidPredicate('z.string().uuid()', undefined, 'import {z} from "zod/v3";')],
      ["UUID string input still admits counterexample", 'import {z} from "zod";const UuidSchema=z.uuid();export function check(value:string):value is string{return UuidSchema.safeParse(value).success;}'],
      ["UUID broad string alias", 'import {z} from "zod";type Text=string;const UuidSchema=z.uuid();export function check(value:unknown):value is Text{return UuidSchema.safeParse(value).success;}'],
      ["UUID standalone arrow", 'import {z} from "zod";const UuidSchema=z.uuid();export const check=(value:unknown):value is string=>UuidSchema.safeParse(value).success;'],
      ["UUID consumed private predicate remains manual", 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}consume(check);'],
      ["UUID separately exported predicate remains manual", 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}export {check};'],
      ["UUID type-observed predicate remains manual", 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}export type Predicate=typeof check;'],
      ["UUID predicate comment remains intact", 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):value is /* reviewed boundary */string{return UuidSchema.safeParse(value).success;}'],
      ["UUID sole named predicate type remains intact", 'import {z} from "zod";type Text=string;const UuidSchema=z.uuid();function check(value:unknown):value is Text{return UuidSchema.safeParse(value).success;}'],
      ["UUID private arrow contract remains manual", 'import {z} from "zod";const UuidSchema=z.uuid();const check=(value:unknown):value is string=>UuidSchema.safeParse(value).success;'],
      ["UUID direct schema export preserves its local native behavior", 'import {z} from "zod";export const UuidSchema=z.uuid();export function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}'],
      ["UUID separate export specifier does not mutate the schema", uuidPredicate()+'export {UuidSchema};'],
      ["UUID original typed exported schema", 'import {z} from "zod";export const UuidSchema:z.ZodUUID=z.uuid();export const check=(value:unknown):value is string=>UuidSchema.safeParse(value).success;'],
      ["UUID namespace type reads do not escape", 'import {z} from "zod";type Schema=z.ZodUUID;const UuidSchema=z.uuid();export function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}'],
    ].map(([name,code])=>({name,code,output:null,errors:[{messageId:'partialPredicate' as const,data:{target:'string',witness:'`"not-a-uuid"`'}}]})),
    { name: "corrects an unused private UUID predicate", code: 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}', output: 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):boolean{return UuidSchema.safeParse(value).success;}', errors: [{ messageId: "partialPredicate" }] },
    { name: "corrects an unused private legacy UUID predicate", code: 'import {z} from "zod";const UuidSchema=z.string().uuid();function check(value:unknown):value is string{return UuidSchema.safeParse(value).success;}', output: 'import {z} from "zod";const UuidSchema=z.string().uuid();function check(value:unknown):boolean{return UuidSchema.safeParse(value).success;}', errors: [{ messageId: "partialPredicate" }] },
    { name: "preserves UUID predicate annotation line breaks", code: 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):value is\nstring{return UuidSchema.safeParse(value).success;}', output: 'import {z} from "zod";const UuidSchema=z.uuid();function check(value:unknown):boolean\n{return UuidSchema.safeParse(value).success;}', errors: [{ messageId: "partialPredicate" }] },
    { name: "preserves the sole named primitive predicate binding", code: "export {}; type Numeric = number; function check(v: unknown): v is Numeric { return typeof v === \"number\" && v > 0; }", output: null, errors: [{ messageId: "partialPredicate" }] },
    { name: "corrects a predicate with an independent exported type use", code: "export type Kept = Numeric; type Numeric = number; function check(v: unknown): v is Numeric { return typeof v === \"number\" && v > 0; }", output: "export type Kept = Numeric; type Numeric = number; function check(v: unknown): boolean { return typeof v === \"number\" && v > 0; }", errors: [{ messageId: "partialPredicate" }] },
    { name: "corrects an unused private positive filter", code: "export {}; function check(v:unknown): v is number { return typeof v === \"number\" && v > 0; }", output: "export {}; function check(v:unknown): boolean { return typeof v === \"number\" && v > 0; }", errors: [{ messageId: "partialPredicate" }] },
    { name: "corrects an unused private truthy string filter", code: "export {}; function check(v:string|null): v is string { return !!v; }", output: "export {}; function check(v:string|null): boolean { return !!v; }", errors: [{ messageId: "partialPredicate" }] },
    { name: "preserves a consumed filter contract", code: "export {}; function check(v:unknown): v is number { return typeof v === \"number\" && v > 0; } consume(check);", output: null, errors: [{ messageId: "partialPredicate" }] },
    { name: "preserves an exported filter contract", code: "export function check(v:unknown): v is number { return typeof v === \"number\" && v > 0; }", output: null, errors: [{ messageId: "partialPredicate" }] },
    { name: "preserves a dynamic private filter reference", code: "export {}; function check(v:unknown): v is number { return typeof v === \"number\" && v > 0; } eval(\"check\");", output: null, errors: [{ messageId: "partialPredicate" }] },
    { name: "preserves useful filter contract comments", code: "export {}; function check(v:unknown): v is /* reviewed boundary */ number { return typeof v === \"number\" && v > 0; }", output: null, errors: [{ messageId: "partialPredicate" }] },
    { name: "public partial guard", code: NO_PARTIAL_TYPE_PREDICATE_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "partialPredicate" }] },
    { name: "NaN remains a number outside all finite bounds", code: predicate('typeof value === "number" && value <= 1e309'), errors: [{ messageId: "partialPredicate", data: { target: "number", witness: "`NaN`" } }] },
    { name: "Infinity diagnostic preserves the actual witness", code: predicate('typeof value === "number" && value < 1e309'), errors: [{ messageId: "partialPredicate", data: { target: "number", witness: "`Infinity`" } }] },
    ...[
      ["positive number", predicate('typeof value === "number" && value > 0')],
      ["numeric enum still has a real rejected member", 'enum Count { Zero=0, One=1 } function check(value: Count): value is number { return value >= 1; }'],
      ["nullable numeric enum retains an actual rejected member", 'enum Count { Zero=0, One=1 } function check(value: Count | null): value is number { return typeof value === "number" && value >= 1; }'],
      ["bounded number", predicate('typeof value === "number" && value < 10')],
      ["nonnegative number", predicate('typeof value === "number" && value >= 0')],
      ["negative literal bound", predicate('typeof value === "number" && value <= -10')],
      ["explicit positive bound", predicate('typeof value === "number" && value > +1')],
      ["selected number", predicate('typeof value === "number" && value === 1')],
      ["excluded number", predicate('typeof value === "number" && value !== 1')],
      ["loose equality within one primitive", predicate('typeof value === "number" && value == 1')],
      ["loose inequality within one primitive", predicate('typeof value === "number" && value != 1')],
      ["reversed typeof", predicate('"number" === typeof value && value > 0')],
      ["loose typeof", predicate('typeof value == "number" && value > 0')],
      ["direct primitive input", predicate("value > 0", "number", "number")],
      ["direct string selection", predicate('value === "ready"', "string", "string")],
      ["nonempty string", predicate('typeof value === "string" && value.length > 0', "string")],
      ["selected length", predicate('typeof value === "string" && value.length === 0', "string")],
      ["excluded length", predicate('typeof value === "string" && value.length !== 1', "string")],
      ["bounded length", predicate('typeof value === "string" && value.length < 10', "string")],
      ["computed length", predicate('typeof value === "string" && value["length"] >= 1', "string")],
      ["selected string", predicate('typeof value === "string" && value === "ready"', "string")],
      ["excluded empty string", predicate('typeof value === "string" && value !== ""', "string")],
      ["string order", predicate('typeof value === "string" && value < "z"', "string")],
      ["positive bigint", predicate('typeof value === "bigint" && value > 0n', "bigint")],
      ["negative bigint bound", predicate('typeof value === "bigint" && value > -1n', "bigint")],
      ["selected boolean", predicate('typeof value === "boolean" && value === true', "boolean")],
      ["boolean self test", predicate('typeof value === "boolean" && value', "boolean")],
      ["direct boolean self test", predicate("value", "boolean", "boolean")],
      ["number truthiness", predicate("!!value", "number", "number | null")],
      ["string truthiness", predicate("!!value", "string", "string | undefined")],
      ["bigint truthiness", predicate("!!value", "bigint", "bigint | undefined")],
      ["boolean truthiness", predicate("!!value", "boolean", "boolean | undefined")],
      ["unknown truthiness is still incomplete", predicate("!!value", "number")],
      ["typeof guarded truthiness", predicate('typeof value === "number" && !!value')],
      ["numeric alias stays broad", 'type Score = number; function check(value: unknown): value is Score { return typeof value === "number" && value > 0; }'],
      ["standalone arrow", 'const check = (value: number): value is number => value > 0;'],
      ["standalone expression", 'const check = function(value: number): value is number { return value > 0; };'],
      ["tests stay checked", predicate('typeof value === "number" && value > 0')],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "partialPredicate" as const }] })),
  ],
});

it("native UUID validation rejects a witness that remains a valid string", () => {
  const witness = "not-a-uuid";
  expect(z.uuid().safeParse(witness).success).toBe(false);
  expect(z.string().uuid().safeParse(witness).success).toBe(false);
  expect(z.string().safeParse(witness).success).toBe(true);
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-partial-type-predicate without a program", rule, {
  valid: [predicate('typeof value === "number" && value > 0')], invalid: [],
});
