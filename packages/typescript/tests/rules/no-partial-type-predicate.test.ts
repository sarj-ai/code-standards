import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

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

TESTER.run("no-partial-type-predicate", rule, {
  valid: [
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
  ],
  invalid: [
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

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-partial-type-predicate without a program", rule, {
  valid: [predicate('typeof value === "number" && value > 0')], invalid: [],
});
