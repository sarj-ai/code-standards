import rule from "../../src/rules/prefer-discriminated-union.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

const RULE_TESTER = ruleTester();
const FAILURE = 'function failure(retry: boolean, saved: boolean): { retriable: boolean; persisted: boolean } { return saved ? { retriable: false, persisted: true } : retry ? { retriable: true, persisted: false } : { retriable: false, persisted: false }; }';
const FAILURE_VARIANTS = FAILURE.replace('{ retriable: boolean; persisted: boolean }', '{ retriable: false; persisted: true } | { retriable: true; persisted: false } | { retriable: false; persisted: false }');

RULE_TESTER.run("prefer-discriminated-union", rule, {
  valid: [
    { name: "literal tag alias chains remain unsupported", code: 'type First="ready"|"waiting";type Phase=First;function state(flag:boolean):{phase:Phase;value?:string}{return flag?{phase:"ready",value:"ready"}:{phase:"waiting"};}' },
    { name: "imported tag aliases remain opaque", code: 'import type {Phase} from "./wire";function state(flag:boolean):{phase:Phase;value?:string}{return flag?{phase:"ready",value:"ready"}:{phase:"waiting"};}' },
    { name: "an unproduced alias tag still prevents a complete domain witness", code: 'type Phase="ready"|"waiting"|"unknown";function state(flag:boolean):{phase:Phase;value?:string}{return flag?{phase:"ready",value:"ready"}:{phase:"waiting"};}' },
    { name: "async thenable carriers do not establish fulfilled variants", code: 'type R={left:boolean;right:boolean;then?:unknown}; function settle(resolve:(value:R)=>void):void { resolve({left:true,right:true}); } async function state(flag:boolean):Promise<R> { return flag?{left:true,right:false,then:settle}:{left:false,right:true,then:settle}; }' },
    { name: "an opaque then property may replace async fulfillment", code: 'declare const then: unknown; async function state(flag:boolean):Promise<{left:boolean;right:boolean;then?:unknown}> { return flag?{left:true,right:false,then}:{left:false,right:true}; }' },
    { name: "default parameter eval can replace the broad switch input", code: `function state(command:string, force:undefined=eval("command='start'")):{phase:"queued"|"complete";ticket?:string}{switch(command){case "start":return{phase:"queued",ticket:"t"};default:return{phase:"complete"};}}` },
    { name: "a const return passed to another observer is not closed", code: 'function state(flag:boolean):{left:boolean;right:boolean}{const value=flag?{left:true,right:false}:{left:false,right:true};observe(value);return value;}' },
    { name: "a const return captured elsewhere is not closed", code: 'function state(flag:boolean):{left:boolean;right:boolean}{const observe=()=>value;const value=flag?{left:true,right:false}:{left:false,right:true};return value;}' },
    { name: "a const alias chain remains unsupported", code: 'function state(flag:boolean):{left:boolean;right:boolean}{const value=flag?{left:true,right:false}:{left:false,right:true};const alias=value;return alias;}' },
    { name: "eval can observe an otherwise closed returned const", code: 'function state(flag:boolean):{left:boolean;right:boolean}{eval("value.left=true");const value=flag?{left:true,right:false}:{left:false,right:true};return value;}' },
    { name: "a Boolean alias containing an unknown state is preserved", code: 'type Bit=boolean|undefined;function state(flag:boolean):{left:Bit;right:Bit}{return flag?{left:true,right:false}:{left:false,right:true};}' },
    { name: "a Boolean alias chain remains unsupported", code: 'type First=boolean;type Bit=First;function state(flag:boolean):{left:Bit;right:Bit}{return flag?{left:true,right:false}:{left:false,right:true};}' },
    { name: "imported Boolean domains are not inferred", code: 'import type {Bit} from "./wire";function state(flag:boolean):{left:Bit;right:Bit}{return flag?{left:true,right:false}:{left:false,right:true};}' },
    { name: "computed dynamic strings remain opaque", code: 'const key="left";function state(flag:boolean):{left:boolean;right:boolean}{return flag?{[key]:true,right:false}:{[key]:false,right:true};}' },
    { name: "preserves independent completing operations", code: 'function state(a: boolean, b: boolean): { observed: boolean; played: boolean } { return a ? b ? { observed: true, played: true } : { observed: true, played: false } : b ? { observed: false, played: true } : { observed: false, played: false }; }' },
    { name: "does not invent a correlation from a constant dimension", code: 'function state(a: boolean): { a: boolean; b: boolean } { return a ? { a: true, b: false } : { a: false, b: false }; }' },
    { name: "does not resolve Boolean expression values or aliases", code: 'function state(a: boolean): { a: boolean; b: boolean } { const b = !a; return a ? { a: true, b } : { a: false, b: true }; }' },
    { name: "does not infer returned object mutation", code: 'function state(a: boolean): { a: boolean; b: boolean } { const state = { a, b: false }; state.b = a; return state; }' },
    { name: "preserves optional unknown observations", code: 'function state(a: boolean): { a: boolean; b?: boolean } { return a ? { a: true, b: false } : { a: false, b: true }; }' },
    { name: "accepts the fixed three-state contract on a second pass", code: `export {}; ${FAILURE_VARIANTS}` },
    { name: "keeps broad partial results without producer evidence", code: 'type PartialResult = { ok: boolean; data?: string; error?: string }; const state: PartialResult = { ok: true, data: "partial", error: "one half failed" };' },
    { name: "does not follow an inherited Boolean contract", code: 'interface Flags { a: boolean; b: boolean } interface State extends Flags {} function state(a: boolean): State { return a ? { a: true, b: false } : { a: false, b: true }; }' },
    { name: "does not cross a try/finally mutation boundary", code: 'function state(a: boolean): { a: boolean; b: boolean } { try { return a ? { a: true, b: false } : { a: false, b: true }; } finally { observe(); } }' },
    { name: "bounds the Boolean pair search without partial findings", code: `function state(a: boolean): { ${Array.from({ length: 9 }, (_, i) => `p${i}: boolean`).join("; ")} } { return a ? { ${Array.from({ length: 9 }, (_, i) => `p${i}: true`).join(", ")} } : { ${Array.from({ length: 9 }, (_, i) => `p${i}: false`).join(", ")} }; }` },
    { name: "public match example", filename: "src/result.ts", code: "type Result = { ok: boolean; data?: string; error?: string };" },
    {
      name: "permits without producer evidence: a direct inline function return shape",
      code: "declare function load(): { ok: boolean; data?: string; error?: string };"
    },
    {
      name: "permits without producer evidence: an inline Promise return shape",
      code: "declare function load(): Promise<{ ok: boolean; data?: string; error?: string }> ;"
    },
    {
      name: "permits without producer evidence: an arrow function inline Promise return shape",
      code: "const load = async (): Promise<{ success: boolean; result?: string; reason?: Error }> => null as never;"
    },
    {
      name: "permits without producer evidence: an inline method return shape",
      code: "class Loader { load(): { ok: boolean; value?: string; cause?: Error } { return null as never; } }"
    },
    {
      name: "permits without producer evidence: an inline function-type return shape",
      code: "type Loader = () => { ok: boolean; payload?: string; errors?: Error[] };"
    },
    {
      name: "permits without producer evidence: a status flag with optional payloads",
      code: "interface Result { success: boolean; data?: string; error?: Error }"
    },
    {
      name: "permits without producer evidence: an interface with success and two optional payloads",
      code: "interface Result { success: boolean; data?: string; error?: string; }"
    },
    {
      name: "permits without producer evidence: a type literal with ok and two optional payloads",
      code: "type Result = { ok: boolean; data?: string; error?: string };"
    },
    {
      name: "permits without producer evidence: more than two optional members",
      code: "interface Outcome { ok: boolean; data?: string; error?: string; warning?: string; retryable?: boolean; }"
    },
    {
      name: "recognizes a string-literal status key",
      code: 'type Result = { "success": boolean; data?: string; error?: string };'
    },
    {
      name: "permits without producer evidence: a success flag with booking and failure branches",
      code: "interface BookingResult { success: boolean; result?: Booking; reason?: string; }"
    },
    {
      name: "permits without producer evidence: an exact success-or-errors interface",
      code: "interface ValidationResult { success: boolean; errors?: ZodIssue[]; }"
    },
    {
      name: "permits without producer evidence: an exact ok-or-error type alias",
      code: "type ParseResult = { ok: boolean; error?: string };"
    },
    {
      name: "permits without producer evidence: an exact success-or-reason inline return",
      code: "declare function validate(): { success: boolean; reason?: string };"
    },
    { name: "does not mistake a symbol key for named status", code: "declare const ok: unique symbol; type Result = { [ok]: boolean; data?: string; error?: Error };" },
    { name: "does not mistake a symbol key for named failure payload", code: "declare const error: unique symbol; type Result = { ok: boolean; [error]?: Error };" },
    { name: "public no-match example", filename: "src/result.ts", code: "type Result = { ok: true; data: string } | { ok: false; error: string };" },
    {
      name: "allows independent all-boolean flag sets",
      code: "interface StateDependencies { data?: boolean; error?: boolean; isValidating?: boolean; isLoading?: boolean }",
    },
    {
      name: "allows an explicit discriminated union",
      code: "type Result = { ok: true; data: string } | { ok: false; error: string };",
    },
    {
      name: "allows an exclusive-property result narrowed with in",
      code: [
        "type Result<T> = { data: T } | { error: string };",
        "declare const result: Result<string>;",
        'if ("error" in result) console.error(result.error);',
      ].join("\n"),
    },
    {
      name: "allows an interface with only one optional payload",
      code: "interface Result { success: boolean; data?: string; }",
    },
    {
      name: "allows a type literal with only one optional payload",
      code: "type Result = { success: boolean; data?: string };",
    },
    {
      name: "allows status flags without optional members",
      code: "interface Flags { ok: boolean; failed: boolean; }",
    },
    {
      name: "allows interfaces without a recognized status member",
      code: "interface Config { host?: string; port?: number; timeout?: number; }",
    },
    {
      name: "allows type literals without a recognized status member",
      code: "type Config = { host?: string; port?: number; timeout?: number };",
    },
    {
      name: "allows a non-boolean member named success",
      code: "interface Response { success: string; data?: string; error?: string; }",
    },
    {
      name: "allows an optional status in partial wire data",
      code: "interface PartialResponse { ok?: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows a negative boolean without a positive result discriminant",
      code: "interface State { isError: boolean; value?: number; cause?: string; }",
    },
    {
      name: "allows independent optional payloads without a failure branch",
      code: "interface TeamResponse { ok: boolean; teamId?: string; url?: string; }",
    },
    {
      name: "allows a failure field when the record also carries independent metadata",
      code: "interface OperationState { success: boolean; errors?: Error[]; requestId: string; }",
    },
    {
      name: "allows aggregate response metadata despite an optional error",
      code: "interface Page { ok: boolean; items?: Item[]; page?: number; error?: string; }",
    },
    {
      name: "takes a false negative for domain-specific branch names",
      code: "interface BookingResult { success: boolean; bookingId?: string; reason?: string; }",
    },
    {
      name: "allows inherited object shapes whose full state is not local",
      code: "interface Result extends Metadata { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows generated declarations",
      filename: "/repo/generated/api.ts",
      code: "interface Result { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows declaration files",
      filename: "/repo/api.d.ts",
      code: "interface Result { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows test fixtures",
      filename: "/repo/result.test.ts",
      code: "interface Result { ok: boolean; data?: string; error?: string; }",
    },
    {
      name: "allows an unrelated boolean member",
      code: "interface Thing { enabled: boolean; data?: string; meta?: number; }",
    },
    {
      name: "allows an optional-only object type",
      code: "type Opts = { a?: number; b?: number; c?: number };",
    },
    {
      name: "allows an empty interface",
      code: "interface Empty {}",
    },
    {
      name: "allows a non-object type alias",
      code: 'type Status = "ok" | "error";',
    },
    {
      name: "allows a named result in a Promise return annotation",
      code: "declare function load(): Promise<Result>;",
    },
    {
      name: "allows an inline return union whose full state is not local",
      code: "declare function load(): { ok: boolean; data?: string; error?: string } | undefined;",
    },
    {
      name: "allows an inline return intersection whose full state is not local",
      code: "declare function load(): Metadata & { ok: boolean; data?: string; error?: string };",
    },
    {
      name: "allows a Promise whose object argument is a union constituent",
      code: "declare function load(): Promise<{ ok: boolean; data?: string; error?: string } | undefined>;",
    },
    {
      name: "allows an inline parameter shape because the function does not produce it",
      code: "declare function consume(value: { ok: boolean; data?: string; error?: string }): void;",
    },
    {
      name: "allows an inline variable annotation",
      code: "declare const result: { ok: boolean; data?: string; error?: string };",
    },
    {
      name: "allows PromiseLike return annotations outside the exact Promise boundary",
      code: "declare function load(): PromiseLike<{ ok: boolean; data?: string; error?: string }>;",
    },
    {
      name: "allows inline return shapes in test fixtures",
      filename: "/repo/result.test.ts",
      code: "declare function load(): Promise<{ ok: boolean; data?: string; error?: string }> ;",
    },
  ],
  invalid: [
    { name: "Boolean aliases preserve payload-over-pair precedence", code: 'type Bit=boolean;function state(flag:boolean):{left:Bit;right:Bit;value?:string}{return flag?{left:true,right:false,value:"ready"}:{left:false,right:true};}', output: null, errors: [{ messageId: "preferProducedVariants" }] },
    { name: "one exact local tag alias preserves payload relationships", code: 'type Phase="ready"|"waiting";function state(flag:boolean):{phase:Phase;value?:string}{return flag?{phase:"ready",value:"ready"}:{phase:"waiting"};}', output: null, errors: [{ messageId: "preferProducedVariants" }] },
    { name: "a Boolean-pair fix preserves independent nullable optional payloads", code: 'export {}; function state(flag: boolean): { left: boolean; right: boolean; trace?: string | null } { return flag ? { left: true, right: false, trace: null } : { left: false, right: true }; }', output: 'export {}; function state(flag: boolean): { left: true; right: false; trace?: string | null } | { left: false; right: true; trace?: string | null } { return flag ? { left: true, right: false, trace: null } : { left: false, right: true }; }', errors: [{ messageId: "preferProducedState" }] },
    { name: "a sole-use local constant exposes literal return variants", code: 'export {}; function state(flag:boolean):{left:boolean;right:boolean}{const value=flag?{left:true,right:false}:{left:false,right:true};return value;}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "as const branches are advisory without annotation rewriting", code: 'export {}; function state(flag:boolean):{left:boolean;right:boolean}{return flag?({left:true,right:false} as const):({left:false,right:true} as const);}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "broad assertions cannot justify a narrowed function annotation", code: 'export {}; type Flat={left:boolean;right:boolean};function state(flag:boolean):{left:boolean;right:boolean}{return flag?({left:true,right:false} as Flat):({left:false,right:true} as Flat);}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "satisfies wrappers expose runtime shapes without an automatic fix", code: 'export {}; type Flat={left:boolean;right:boolean};function state(flag:boolean):{left:boolean;right:boolean}{return flag?({left:true,right:false} satisfies Flat):({left:false,right:true} satisfies Flat);}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "independent nullable payloads do not erase Boolean evidence", code: 'export function state(flag:boolean):{left:boolean;right:boolean;payload?:string|null}{return flag?{left:true,right:false,payload:null}:{left:false,right:true};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "explicit undefined payloads preserve independent Boolean evidence", code: 'export function state(flag:boolean):{left:boolean;right:boolean;payload?:string|undefined}{return flag?{left:true,right:false,payload:undefined}:{left:false,right:true};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "literal Boolean domains admit both values", code: 'export function state(flag:boolean):{left:true|false;right:false|true}{return flag?{left:true,right:false}:{left:false,right:true};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "one local Boolean alias admits both values", code: 'type Bit=boolean;export function state(flag:boolean):{left:Bit;right:Bit}{return flag?{left:true,right:false}:{left:false,right:true};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "value namespace shadows do not change Boolean type aliases", code: 'type Bit=true|false;export function state(flag:boolean,Bit:number):{left:Bit;right:Bit}{return flag?{left:true,right:false}:{left:false,right:true};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "literal computed string keys have a known identity", code: 'export function state(flag:boolean):{["left"]:boolean;["right"]:boolean}{return flag?{["left"]:true,["right"]:false}:{["left"]:false,["right"]:true};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "noncallable then values preserve the async carrier", code: 'async function state(flag:boolean):Promise<{left:boolean;right:boolean;then?:0}>{return flag?{left:true,right:false,then:0}:{left:false,right:true,then:0};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "synchronous thenable objects keep their direct identity", code: 'declare const then:unknown;function state(flag:boolean):{left:boolean;right:boolean;then?:unknown}{return flag?{left:true,right:false,then}:{left:false,right:true,then};}', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "retains one payload advisory for a present-or-absent observation", code: 'function state(a: boolean): { a: boolean; b?: boolean } { return a ? { a: true, b: false } : { a: false }; }', output: null, errors: [{ messageId: "preferProducedVariants" }] },
    { name: "refines the three failure dispositions without runtime changes", code: `export {}; ${FAILURE}`, output: `export {}; ${FAILURE_VARIANTS}`, errors: [{ messageId: "preferProducedState", data: { fields: "retriable`, `persisted" } }] },
    { name: "requires review when callers observe the producer", code: `export {}; ${FAILURE} const alias = failure; alias(true, false);`, output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "preserves contracts exposed through a type query", code: `export {}; ${FAILURE} export type API = ReturnType<typeof failure>;`, output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "preserves script-global functions", code: FAILURE, output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "preserves dynamically observed declarations", code: `export {}; ${FAILURE} eval("failure");`, output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "preserves all native line terminators in annotation fixes", code: `export {}; ${FAILURE.replace('retriable: boolean;', 'retriable:\u2028boolean;').replace('persisted: boolean', 'persisted:\u2029boolean')}`, output: `export {}; ${FAILURE_VARIANTS.replace(' { return', '\u2028\u2029 { return')}`, errors: [{ messageId: "preferProducedState" }] },
    { name: "keeps a shared historical-observation contract broad when another writer needs the fourth state", code: 'type Observations = { heard: boolean; reported: boolean }; const historical: Observations = { heard: true, reported: true }; function current(a: boolean, b: boolean): Observations { return a ? { heard: true, reported: false } : b ? { heard: false, reported: true } : { heard: false, reported: false }; }', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "preserves expression-valued payload side effects for manual review", code: 'export {}; declare function publish(): number; ' + FAILURE.replace('{ retriable: boolean; persisted: boolean }', '{ retriable: boolean; persisted: boolean; value?: number }').replace('{ retriable: false, persisted: true }', '{ retriable: false, persisted: true, value: publish() }'), output: null, errors: [{ messageId: "preferProducedVariants" }] },
    { name: "preserves an exported failure interface", code: `export ${FAILURE}`, output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "observes async correlations but preserves async boundaries", code: 'async function state(a: boolean): Promise<{ a: boolean; b: boolean }> { await checkpoint(); return a ? { a: true, b: false } : { a: false, b: true }; }', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "reports a shared contract once despite multiple producers", code: 'type State = { a: boolean; b: boolean }; function one(a: boolean): State { return a ? { a: true, b: false } : { a: false, b: true }; } function two(a: boolean): State { return a ? { a: true, b: false } : { a: false, b: true }; }', output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "gives payload evidence precedence over Boolean evidence", code: 'function state(a: boolean): { a: boolean; b: boolean; value?: string } { return a ? { a: true, b: false, value: "ready" } : { a: false, b: true }; }', output: null, errors: [{ messageId: "preferProducedVariants" }] },
    { name: "preserves the named type of a never produced optional field", code: "export {}; type Extra = string; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string; extra?: Extra } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", output: null, errors: [{ messageId: "preferProducedVariants" }] },
    { name: "refines variants when the removed field type has an exported use", code: "export type Kept = Extra; type Extra = string; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string; extra?: Extra } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", output: "export type Kept = Extra; type Extra = string; function job(done: boolean): { phase: \"complete\" } | { phase: \"queued\"; ticket: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", errors: [{ messageId: "preferProducedVariants" }] },
    {name: "corrects an unused private literal producer", code: "export {}; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", output: "export {}; function job(done: boolean): { phase: \"complete\" } | { phase: \"queued\"; ticket: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", errors: [{messageId: "preferProducedVariants"}]},
    {name: "preserves consumed producer contracts", code: "export {}; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; } consume(job);", output: null, errors: [{messageId: "preferProducedVariants"}]},
    {name: "preserves exported producer contracts", code: "export {}; export function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", output: null, errors: [{messageId: "preferProducedVariants"}]},
    {name: "preserves producer contract comments", code: "export {}; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: /* owned */ string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: \"t\" }; }", output: null, errors: [{messageId: "preferProducedVariants"}]},
    {name: "preserves expression payload inference", code: "export {}; function job(done: boolean): { phase: \"queued\" | \"complete\"; ticket?: string } { return done ? { phase: \"complete\" } : { phase: \"queued\", ticket: existingTicket }; }", output: null, errors: [{messageId: "preferProducedVariants"}]},

  ],
});
const PHASE_SOURCE = 'type Phase = "ready" | "waiting" | "reconnecting"; declare function snapshot(): Phase;';
const PROJECTION = `${PHASE_SOURCE} function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; }`;
const PROJECTED_ERROR = { messageId: "preferProjectedState", data: { fields: "ready`, `waiting" } };
const TYPED_RULE_TESTER = ruleTester({ cwd: FIXTURES });

TYPED_RULE_TESTER.run("prefer-discriminated-union immutable projections", rule, typed({
  valid: [
    { name: "type services disabled leaves the syntax-only owner active", code: PROJECTION, settings: { sarj: { typeAware: false } } },
    { name: "independent operations can both complete", code: `${PHASE_SOURCE} function state(): { ready: boolean; waiting: boolean } { const first = snapshot(); const second = snapshot(); return { ready: first === "ready", waiting: second === "waiting" }; }` },
    { name: "historical observations may coexist with the current phase", code: `${PHASE_SOURCE} function state(started: boolean): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: started, waiting: phase === "waiting" }; }` },
    { name: "partial results preserve independent payloads", code: `${PHASE_SOURCE} function state(data?: string, error?: string): { ready: boolean; waiting: boolean; data?: string | undefined; error?: string | undefined } { const first = snapshot(); const second = snapshot(); return { ready: first === "ready", waiting: second === "waiting", data, error }; }` },
    { name: "let bindings can change between comparisons", code: PROJECTION.replace("const phase", "let phase") },
    { name: "a mutable closure does not prove a snapshot", code: `${PHASE_SOURCE} function state(): { ready: boolean; waiting: boolean } { let phase = snapshot(); const update = () => { phase = snapshot(); }; update(); return { ready: phase === "ready", waiting: phase === "waiting" }; }` },
    { name: "object aliases do not freeze their properties", code: `${PHASE_SOURCE} function state(): { ready: boolean; waiting: boolean } { const box = { phase: snapshot() }; const alias = box; return { ready: alias.phase === "ready", waiting: box.phase === "waiting" }; }` },
    { name: "getters may yield different phases", code: `${PHASE_SOURCE} function state(): { ready: boolean; waiting: boolean } { const box = { get phase() { return snapshot(); } }; return { ready: box.phase === "ready", waiting: box.phase === "waiting" }; }` },
    { name: "async producers remain unsupported", code: PROJECTION.replace("function state():", "async function state(): Promise<").replace("boolean } {", "boolean }> {") },
    { name: "await boundaries remain unsupported", code: PROJECTION.replace("function state():", "async function state(): Promise<").replace("boolean } {", "boolean }> {").replace("return {", "await Promise.resolve(); return {") },
    { name: "other own return paths can admit both true", code: PROJECTION.replace("function state()", "function state(flag: boolean)").replace("return {", "if (flag) return { ready: true, waiting: true }; return {") },
    { name: "module captures are outside producer ownership", code: `${PHASE_SOURCE} const phase = snapshot(); function state(): { ready: boolean; waiting: boolean } { return { ready: phase === "ready", waiting: phase === "waiting" }; }` },
    { name: "parameters are outside the local const scope", code: 'function state(phase: "ready" | "waiting"): { ready: boolean; waiting: boolean } { return { ready: phase === "ready", waiting: phase === "waiting" }; }' },
    { name: "open string domains remain accepted", code: PROJECTION.replace('type Phase = "ready" | "waiting" | "reconnecting"', "type Phase = string") },
    { name: "nullable domains remain unsupported", code: PROJECTION.replace('"reconnecting"', '"reconnecting" | null') },
    { name: "constant dimensions are not state pairs", code: PROJECTION.replace('phase === "waiting"', 'phase === "ready"') },
    { name: "flow-narrowed constant dimensions abstain", code: PROJECTION.replace('return {', 'if (phase !== "ready") throw new Error(); return {') },
    { name: "loose equality stays unsupported", code: PROJECTION.replaceAll("===", "==") },
    { name: "spreads conceal returned fields", code: PROJECTION.replace("return {", "return { ...{},") },
    { name: "a generic contract requires cross-instantiation review", code: PROJECTION.replace("function state()", "function state<T>()") },
    { name: "inherited contracts stay with their existing owner", code: `${PHASE_SOURCE} interface Base { ready: boolean; waiting: boolean } interface State extends Base {} function state(): State { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; }` },
    { name: "optional dimensions remain accepted", code: PROJECTION.replace("waiting: boolean }", "waiting?: boolean }") },
    { name: "dynamic eval can invalidate const assumptions", code: PROJECTION.replace("return {", 'eval("phase"); return {') },
    { name: "an enum namespace escape permits mutation", code: 'enum Phase { Ready = "ready", Waiting = "waiting" } declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); Object.assign(Phase, { Ready: "waiting" }); return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }' },
    { name: "writes through erased namespace wrappers abstain", code: 'enum Phase { Ready = "ready", Waiting = "waiting" } declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); (Phase as { Ready: string }).Ready = "waiting"; return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }' },
    { name: "namespace aliasing stays unsupported", code: 'enum Phase { Ready = "ready", Waiting = "waiting" } declare function snapshot(): Phase; const alias = Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === alias.Ready, waiting: phase === alias.Waiting }; }' },
    { name: "an imported object typed as an enum is not its declaration", code: 'import { lookalike as Phase } from "../state-projection-domain"; declare function snapshot(): import("../state-projection-domain").Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }' },
    { name: "enum aliases with the same runtime value do not establish exclusion", code: 'enum Phase { Ready = "same", Waiting = "same" } declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }' },
    { name: "merged enum namespaces stay unsupported", code: 'enum Phase { Ready = "ready", Waiting = "waiting" } namespace Phase { export const Other = "other"; } declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }' },
    { name: "computed enum reads remain unsupported", code: 'enum Phase { Ready = "ready", Waiting = "waiting" } declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === Phase["Ready"], waiting: phase === Phase.Waiting }; }' },
    { name: "symbol domains remain unsupported", code: 'declare const ready: unique symbol; declare const waiting: unique symbol; declare function snapshot(): typeof ready | typeof waiting; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === ready, waiting: phase === waiting }; }' },
    { name: "bounds finite domains conservatively", code: PROJECTION.replace('"reconnecting"', Array.from({ length: 15 }, (_, i) => `"other${i}"`).join(" | ")) },
    { name: "bounds Boolean fields conservatively", code: PROJECTION.replace("waiting: boolean }", `waiting: boolean; ${Array.from({ length: 7 }, (_, i) => `p${i}: boolean`).join("; ")} }`).replace('waiting: phase === "waiting"', `waiting: phase === "waiting", ${Array.from({ length: 7 }, (_, i) => `p${i}: true`).join(", ")}`) },
    { name: "exceeding the file pair budget emits no partial typed findings", code: `${PHASE_SOURCE} ${Array.from({ length: 129 }, (_, i) => PROJECTION.slice(PHASE_SOURCE.length).replace("function state()", `function state${i}()`)).join("\n")}` },
    { name: "a typed state preserves unknown and reconnecting states", code: 'type Phase = "ready" | "waiting" | "reconnecting" | "unknown"; declare function snapshot(): Phase; function state(timeout: boolean): { phase: Phase; timeout: boolean } { const phase = snapshot(); return { phase, timeout }; }' },
  ].map((test) => ({ filename: "src/projection.ts", ...test })),
  invalid: [
    { name: "finite string comparisons expose a representation gap without an autofix", code: PROJECTION, output: null, errors: [PROJECTED_ERROR] },
    { name: "public immutable projection match example", code: 'type Phase = "ready" | "waiting" | "unknown"; declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; }', output: null, errors: [PROJECTED_ERROR] },
    { name: "primitive aliases keep their own immutable identity", code: PROJECTION.replace("const phase = snapshot();", "const original = snapshot(); const phase = original;"), output: null, errors: [PROJECTED_ERROR] },
    { name: "destructured snapshots preserve independent timeout and partial data", code: 'import { Phase as ConnectionPhase } from "../state-projection-domain"; declare function useSnapshot(): [ConnectionPhase, (next: ConnectionPhase) => void]; interface State { ready: boolean; waiting: boolean; timeout: boolean; data?: string | undefined; error?: string | undefined } function state(timeout: boolean, data?: string, error?: string): State { const [phase, setPhase] = useSnapshot(); const update = () => setPhase(ConnectionPhase.Closed); update(); return { ready: phase === ConnectionPhase.Ready, waiting: phase === ConnectionPhase.Waiting, timeout, data, error }; }', output: null, errors: [PROJECTED_ERROR] },
    { name: "object destructuring copies a primitive snapshot", code: PROJECTION.replace("const phase = snapshot();", "const { phase } = { phase: snapshot() };"), output: null, errors: [PROJECTED_ERROR] },
    { name: "read-only callbacks do not mutate a primitive snapshot", code: PROJECTION.replace("return {", "const read = () => phase; read(); return {"), output: null, errors: [PROJECTED_ERROR] },
    { name: "nested callback returns do not count as producer returns", code: PROJECTION.replace("return {", "const read = () => { return phase; }; read(); return {"), output: null, errors: [PROJECTED_ERROR] },
    { name: "state reads before callbacks remain one snapshot", code: PROJECTION.replace('waiting: phase === "waiting"', 'waiting: phase === "waiting"').replace("return {", "Promise.resolve().then(() => snapshot()); return {"), output: null, errors: [PROJECTED_ERROR] },
    { name: "numeric literals compare raw values", code: PROJECTION.replace('"ready" | "waiting" | "reconnecting"', "0 | 1 | 2").replaceAll('=== "ready"', "=== 0").replaceAll('=== "waiting"', "=== 1"), output: null, errors: [PROJECTED_ERROR] },
    { name: "local enum declarations establish constant provenance", code: 'enum Phase { Ready = "ready", Waiting = "waiting", Unknown = "unknown" } declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }', output: null, errors: [PROJECTED_ERROR] },
    { name: "reexported imported enums retain declaration identity", code: 'import { ReexportedPhase as Phase } from "../state-projection-domain"; declare function snapshot(): Phase; function state(): { ready: boolean; waiting: boolean } { const phase = snapshot(); return { ready: phase === Phase.Ready, waiting: phase === Phase.Waiting }; }', output: null, errors: [PROJECTED_ERROR] },
    { name: "local aliases and Boolean aliases reuse existing contract resolution", code: `type Bit = true | false; type State = { ready: Bit; waiting: Bit }; ${PHASE_SOURCE} function state(): State { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; }`, output: null, errors: [PROJECTED_ERROR] },
    { name: "shared contracts report once across producers", code: `type State = { ready: boolean; waiting: boolean }; ${PHASE_SOURCE} function first(): State { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; } function second(): State { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; }`, output: null, errors: [PROJECTED_ERROR] },
    { name: "literal evidence retains diagnostic ownership over a shared contract", code: `type State = { ready: boolean; waiting: boolean }; ${PHASE_SOURCE} function first(): State { const phase = snapshot(); return { ready: phase === "ready", waiting: phase === "waiting" }; } function second(flag: boolean): State { return flag ? { ready: true, waiting: false } : { ready: false, waiting: true }; }`, output: null, errors: [{ messageId: "preferProducedState" }] },
    { name: "the finite domain boundary remains supported", code: PROJECTION.replace('"reconnecting"', Array.from({ length: 14 }, (_, i) => `"other${i}"`).join(" | ")), output: null, errors: [PROJECTED_ERROR] },
    { name: "disabling types preserves existing literal-producer diagnostics", code: 'function state(flag: boolean): { ready: boolean; waiting: boolean } { return flag ? { ready: true, waiting: false } : { ready: false, waiting: true }; }', settings: { sarj: { typeAware: false } }, output: null, errors: [{ messageId: "preferProducedState" }] },
  ].map((test) => ({ filename: "src/projection.ts", ...test })),
}));
