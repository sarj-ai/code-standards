// vitest: shared-module-graph
import rule from "../../src/rules/prefer-discriminated-union.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();
const FAILURE = 'function failure(retry: boolean, saved: boolean): { retriable: boolean; persisted: boolean } { return saved ? { retriable: false, persisted: true } : retry ? { retriable: true, persisted: false } : { retriable: false, persisted: false }; }';
const FAILURE_VARIANTS = FAILURE.replace('{ retriable: boolean; persisted: boolean }', '{ retriable: false; persisted: true } | { retriable: true; persisted: false } | { retriable: false; persisted: false }');

RULE_TESTER.run("prefer-discriminated-union", rule, {
  valid: [
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
