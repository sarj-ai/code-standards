// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_DISCRIMINATED_UNION_DOCUMENTATION } from "../../src/rules/prefer-discriminated-union.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const JOB_SHAPE = '{ phase: "queued" | "complete"; ticket?: string }';
const JOB_BODY = 'if (n) return { phase: "queued", ticket: "t" }; return { phase: "complete" };';
const SWITCH_BODY = 'switch (command) { case "start": return { phase: "queued", ticket: "t" }; default: return { phase: "complete" }; }';

function producer(body = JOB_BODY, annotation = JOB_SHAPE): string {
  return `function job(n: boolean): ${annotation} { ${body} }`;
}

function dispatch(body = SWITCH_BODY, input = "string", annotation = JOB_SHAPE): string {
  return `function job(command: ${input}): ${annotation} { ${body} }`;
}

const PRODUCER_EXAMPLES = PREFER_DISCRIMINATED_UNION_DOCUMENTATION.examples.filter(
  (example) => "scenarioId" in example && example.scenarioId === "produced-variants",
);

RULE_TESTER.run("prefer-discriminated-union", rule, {
  valid: [
    ...PRODUCER_EXAMPLES.filter((example) => example.outcome === "no-match").map((example) => ({ name: example.id, filename: example.focusPath, code: example.files[0].source })),
    { name: "optional fields alone do not prove an invalid state", code: `type Job = ${JOB_SHAPE};` },
    { name: "explicit union already preserves payload correlation", code: producer(JOB_BODY, '{ phase: "queued"; ticket: string } | { phase: "complete" }') },
    { name: "partial snapshots can vary payload presence under the same tag", code: producer('if (n) return { phase: "queued", ticket: "t" }; if (other) return { phase: "queued" }; return { phase: "complete" };') },
    { name: "payload presence independent of tag stays optional", code: producer('if (n) return { phase: "queued", ticket: "t" }; return { phase: "complete", ticket: "u" };') },
    { name: "all declared variants must be witnessed", code: producer(JOB_BODY, '{ phase: "queued" | "complete" | "failed"; ticket?: string }') },
    { name: "unknown tags belong to the compiler", code: producer('if (n) return { phase: "queued", ticket: "t" }; return { phase: "unknown" };') },
    { name: "open string tag does not prove a finite domain", code: producer(JOB_BODY, '{ phase: string; ticket?: string }') },
    { name: "optional tag is not a reliable discriminator", code: producer(JOB_BODY, '{ phase?: "queued" | "complete"; ticket?: string }') },
    { name: "mixed open tag union is not finite", code: producer(JOB_BODY, '{ phase: "queued" | string; ticket?: string }') },
    { name: "dynamic tags do not prove field correlation", code: producer('if (n) return { phase, ticket: "t" }; return { phase: "complete" };') },
    { name: "inline outer union has a larger contract", code: producer(JOB_BODY, `${JOB_SHAPE} | undefined`) },
    { name: "inline intersection has unresolved members", code: producer(JOB_BODY, `${JOB_SHAPE} & Metadata`) },
    { name: "aliases of outer unions have a larger contract", code: `type Job = ${JOB_SHAPE} | undefined; ${producer(JOB_BODY, 'Job')}` },
    { name: "aliases of intersections have unresolved members", code: `type Job = ${JOB_SHAPE} & Metadata; ${producer(JOB_BODY, 'Job')}` },
    { name: "imported contracts are external", code: `import type { Job } from "wire"; ${producer(JOB_BODY, 'Job')}` },
    { name: "inherited interfaces may define broader invariants", code: `interface Job extends Metadata ${JOB_SHAPE} ${producer(JOB_BODY, 'Job')}` },
    { name: "interface merging changes the full contract", code: `interface Job ${JOB_SHAPE} interface Job { metadata?: string } ${producer(JOB_BODY, 'Job')}` },
    { name: "generic parameters shadow outer type aliases", code: `type Job = ${JOB_SHAPE}; function job<Job>(n: boolean): Job { ${JOB_BODY} }` },
    { name: "local type aliases shadow outer declarations", code: `type Job = ${JOB_SHAPE}; function scope() { type Job = { phase: string; ticket?: string }; ${producer(JOB_BODY, 'Job')} }` },
    { name: "generic type alias instantiation is intentionally unresolved", code: `type Job<T> = { phase: "queued" | "complete"; ticket?: T }; ${producer(JOB_BODY, 'Job<string>')}` },
    { name: "qualified type references are intentionally unresolved", code: producer(JOB_BODY, 'Types.Job') },
    { name: "shadowed Promise is not the async container", code: `type Promise<T> = ${JOB_SHAPE}; async function job(n: boolean): Promise<string> { ${JOB_BODY} }` },
    { name: "PromiseLike is not the exact async boundary", code: `async function job(n: boolean): PromiseLike<${JOB_SHAPE}> { ${JOB_BODY} }` },
    { name: "synchronous producer does not unwrap Promise", code: producer(JOB_BODY, `Promise<${JOB_SHAPE}>`) },
    { name: "nested function returns cannot witness outer tags", code: producer('function nested() { return { phase: "queued", ticket: "t" }; } return { phase: "complete" };') },
    { name: "constant false branches cannot witness tags", code: producer('if (false) return { phase: "queued", ticket: "t" }; return { phase: "complete" };') },
    { name: "constant conditional alternatives cannot witness tags", code: `const job = (): ${JOB_SHAPE} => true ? { phase: "queued", ticket: "t" } : { phase: "complete" };` },
    { name: "unreachable returns cannot witness tags", code: producer('return { phase: "complete" }; return { phase: "queued", ticket: "t" };') },
    { name: "every completion path must return or throw", code: producer('if (n) return { phase: "queued", ticket: "t" }; if (other) return { phase: "complete" };') },
    { name: "bare return loses local evidence", code: producer(`${JOB_BODY.replace('return { phase: "complete" };', 'if (other) return { phase: "complete" }; return;')}`) },
    { name: "dynamic return value loses local evidence", code: producer('if (n) return { phase: "queued", ticket: "t" }; if (other) return { phase: "complete" }; return cached;') },
    { name: "unknown conditional alternatives lose local evidence", code: `const job = (n: number): ${JOB_SHAPE} => n === 1 ? { phase: "queued", ticket: "t" } : n === 2 ? { phase: "complete" } : cached;` },
    { name: "loop completion is intentionally unmodeled", code: producer('while (n) { return { phase: "queued", ticket: "t" }; } return { phase: "complete" };') },
    { name: "finally can replace earlier returns", code: producer(`try { ${JOB_BODY} } finally { return cached; }`) },
    { name: "closed switch input remains deliberately unmodeled", code: producer('switch (n) { case true: return { phase: "queued", ticket: "t" }; default: return { phase: "complete" }; }') },
    { name: "explicit switch union already retains the correlation", code: dispatch(SWITCH_BODY, "string", '{ phase: "queued"; ticket: string } | { phase: "complete" }') },
    { name: "switch may fall through without a default", code: dispatch('switch(command) { case "start": return {phase:"queued",ticket:"t"}; case "finish": return {phase:"complete"}; }') },
    { name: "break leaves switch completion unresolved", code: dispatch('switch(command) { case "start": return {phase:"queued",ticket:"t"}; default: break; } return {phase:"complete"};') },
    { name: "nonempty fallthrough may affect later branches", code: dispatch('switch(command) { case "start": log(); default: return {phase:"complete"}; }') },
    { name: "conditional fallthrough cannot establish terminal groups", code: dispatch('switch(command) { case "start": if (n) return {phase:"queued",ticket:"t"}; default: return {phase:"complete"}; }') },
    { name: "default conditions cannot invent a previously matched case", code: dispatch('switch(command){case "start":return {phase:"queued",ticket:"t"};default:if(command==="start")return {phase:"complete"};return {phase:"queued",ticket:"t"};}') },
    { name: "case conditions cannot invent an excluded input", code: dispatch('switch(command){case "start":if(command!=="start")return {phase:"complete"};return {phase:"queued",ticket:"t"};default:return {phase:"queued",ticket:"t"};}') },
    { name: "conditional switch returns require separate reachability evidence", code: dispatch('switch(command){case "start":return {phase:"queued",ticket:"t"};default:return command==="start"?{phase:"complete"}:{phase:"queued",ticket:"t"};}') },
    { name: "effect prefixes are outside flat terminal case evidence", code: dispatch(SWITCH_BODY.replace('case "start":','case "start":log();')) },
    { name: "nested block prefixes are outside flat terminal case evidence", code: dispatch(SWITCH_BODY.replace('return { phase: "queued", ticket: "t" };','{log();return {phase:"queued",ticket:"t"};}')) },
    { name: "case branches with nested conditions remain unmodeled", code: dispatch(SWITCH_BODY.replace('return { phase: "queued", ticket: "t" };','if(n)return {phase:"queued",ticket:"t"};return {phase:"queued",ticket:"u"};')) },
    { name: "trailing empty label can finish without returning", code: dispatch('switch(command) { case "start": return {phase:"queued",ticket:"t"}; default: return {phase:"complete"}; case "stop": }') },
    { name: "duplicate labels have unreachable alternatives", code: dispatch('switch(command) { case "start": return {phase:"queued",ticket:"t"}; case "start": return {phase:"complete"}; default: throw Error(); }') },
    { name: "case labels of another kind are unreachable", code: dispatch(SWITCH_BODY.replace('case "start"', 'case 1')) },
    { name: "dynamic labels are not evaluated", code: dispatch(SWITCH_BODY.replace('case "start"', 'case commandName')) },
    { name: "effectful case tests are not inferred", code: dispatch(SWITCH_BODY.replace('case "start"', 'case commandName()')) },
    { name: "closed literal parameter can make default unreachable", code: dispatch(SWITCH_BODY, '"start"') },
    { name: "finite input is outside broad-parameter witness proof", code: dispatch(SWITCH_BODY, '"start" | "finish"') },
    { name: "generic input is unresolved", code: 'function job<T extends string>(command:T): '+JOB_SHAPE+' {'+SWITCH_BODY+'}' },
    { name: "aliased input is outside local witness proof", code: 'type Command = string; '+dispatch(SWITCH_BODY,'Command') },
    { name: "unknown switch input stays conservative", code: dispatch(SWITCH_BODY,'unknown') },
    { name: "constant switch cannot witness all cases", code: dispatch(SWITCH_BODY.replace('switch (command)', 'switch ("start")')) },
    { name: "captured broad variable need not retain declared input domain", code: 'const command:string="start"; function job(): '+JOB_SHAPE+' {'+SWITCH_BODY+'}' },
    { name: "public overload can exclude the implementation default", code: 'function job(command:"start"):'+JOB_SHAPE+';'+dispatch() },
    { name: "body binding cannot hide the public overload declarations", code:'function job(command:"start"):'+JOB_SHAPE+';'+dispatch(SWITCH_BODY.replace('case "start":','case "start":var job=1;')) },
    { name: "parameter binding cannot hide the public overload declarations", code:'function job(command:"start",job?:unknown):'+JOB_SHAPE+';'+dispatch().replace('command: string','command: string,job?:unknown') },
    { name: "parameter shadowing loses the callable declaration proof", code:dispatch().replace('command: string','command: string,job?:unknown') },
    { name: "contextual callback can exclude implementation default", code: 'const job:(command:"start")=>'+JOB_SHAPE+'=(command:string):'+JOB_SHAPE+'=>{'+SWITCH_BODY+'};' },
    { name: "object method can have independently owned input domain", code:'const adapter:{job(command:"start"):'+JOB_SHAPE+'}={job(command:string):'+JOB_SHAPE+'{'+SWITCH_BODY+'}};' },
    { name: "inherited class method can have separate public domain", code:'class Base{job(command:"start"):'+JOB_SHAPE+'{return {phase:"queued",ticket:"t"};}}class Child extends Base{job(command:string):'+JOB_SHAPE+'{'+SWITCH_BODY+'}}' },
    { name: "rewritten parameter can make a case unreachable", code: dispatch('command="start"; '+SWITCH_BODY) },
    { name: "captured mutation loses immutable input evidence", code: dispatch('switch(command){case "start":function mutate(){command="start";} return {phase:"queued",ticket:"t"};default:return {phase:"complete"};}') },
    { name: "preceding narrow can make default unreachable", code: dispatch('if(command!=="start")throw Error(); '+SWITCH_BODY) },
    { name: "nested narrowed switch cannot establish broad input witnesses", code: dispatch('if(command==="start"){'+SWITCH_BODY+'}return {phase:"complete"};') },
    { name: "try can change switch completions", code: dispatch('try {'+SWITCH_BODY+'} finally {return cached;}') },
    { name: "dynamic case result loses the output contract", code: dispatch(SWITCH_BODY.replace('{ phase: "complete" }','cached')) },
    { name: "inconsistent per-tag presence remains a snapshot", code: dispatch('switch(command){case "start":return {phase:"queued",ticket:"t"};case "retry":return {phase:"queued"};default:return {phase:"complete"};}') },
    { name: "missing declared tag remains unknown domain evidence", code: dispatch(SWITCH_BODY,'string','{phase:"queued"|"complete"|"failed";ticket?:string}') },
    { name: "shared payload on every tag is independent", code: dispatch(SWITCH_BODY.replace('{ phase: "complete" }','{ phase: "complete",ticket:"u" }')) },
    { name: "switch return count budget abstains", code: dispatch('switch(command){'+Array.from({length:257},(_,n)=>`case "${n}":return {phase:"queued",ticket:"t"};`).join('')+'default:return {phase:"complete"};}') },
    { name: "switch sole block depth budget abstains", code: dispatch(SWITCH_BODY.replace('return { phase: "queued", ticket: "t" };','{'.repeat(80)+'return {phase:"queued",ticket:"t"};'+'}'.repeat(80))) },
    { name: "simple path visits budget abstains", code: producer('let x=0;'.repeat(2100)+JOB_BODY) },
    { name: "conditional depth budget abstains", code: `const job=(n:number):${JOB_SHAPE}=>`+'n?'.repeat(80)+'{phase:"queued",ticket:"t"}'+':{phase:"complete"}'.repeat(80)+';' },
    { name: "generator protocol is not a producer return contract", code: `function* job(n: boolean): ${JOB_SHAPE} { ${JOB_BODY} }` },
    { name: "spread can replace visible properties", code: producer('if (n) return { ...metadata, phase: "queued", ticket: "t" }; return { phase: "complete" };') },
    { name: "computed keys may conceal runtime shape", code: producer('if (n) return { ["phase"]: "queued", ticket: "t" }; return { phase: "complete" };') },
    { name: "computed symbol keys are not plain payload fields", code: `const ticket = Symbol(); ${producer('if (n) return { phase: "queued", [ticket]: "t" }; return { phase: "complete" };', '{ phase: "queued" | "complete"; [ticket]?: string }')}` },
    { name: "accessor payloads have different runtime semantics", code: producer('if (n) return { phase: "queued", get ticket() { return "t"; } }; return { phase: "complete" };') },
    { name: "prototype setter is not an own payload key", code: producer('if (n) return { phase: "queued", __proto__: prototype }; return { phase: "complete" };', '{ phase: "queued" | "complete"; __proto__?: object }') },
    { name: "duplicate object properties lose stable evidence", code: producer('if (n) return { phase: "queued", ticket: "t", ticket: "u" }; return { phase: "complete" };') },
    { name: "duplicate declaration properties lose stable evidence", code: producer(JOB_BODY, '{ phase: "queued" | "complete"; ticket?: string; ticket?: string }') },
    { name: "index signatures do not define a complete local key set", code: producer(JOB_BODY, '{ phase: "queued" | "complete"; ticket?: string; [key: string]: unknown }') },
    { name: "invalid missing required fields belong to compiler", code: producer(JOB_BODY, '{ phase: "queued" | "complete"; id: string; ticket?: string }') },
    { name: "invalid excess fields belong to compiler", code: producer('if (n) return { phase: "queued", ticket: "t", other: 1 }; return { phase: "complete" };') },
    { name: "explicit undefined payload is not useful required data", code: producer('if (n) return { phase: "queued", ticket: undefined }; return { phase: "complete" };', '{ phase: "queued" | "complete"; ticket?: string | undefined }') },
    { name: "void payload is not useful required data", code: producer('if (n) return { phase: "queued", ticket: void 0 }; return { phase: "complete" };', '{ phase: "queued" | "complete"; ticket?: string | undefined }') },
    { name: "null payload remains intentionally conservative", code: producer('if (n) return { phase: "queued", ticket: null }; return { phase: "complete" };', '{ phase: "queued" | "complete"; ticket?: string | null }') },
    { name: "exact-code suppression preserves required wider contracts", code: `// eslint-disable-next-line @rule-tester/prefer-discriminated-union -- Required external snapshot contract.\ntype Job = ${JOB_SHAPE}; ${producer(JOB_BODY, 'Job')}` },
    { name: "generated ownership marker excludes producers", code: `// @generated\n${producer()}` },
    { name: "test fixture path excludes producers", filename: '/repo/job.test.ts', code: producer() },
    { name: "declaration fixture path excludes producers", filename: '/repo/job.d.ts', code: producer() },
  ],
  invalid: [
    ...PRODUCER_EXAMPLES.filter((example) => example.outcome === "match").map((example) => ({ name: example.id, filename: example.focusPath, code: example.files[0].source, errors: [{ messageId: 'preferProducedVariants' as const, data: { tag: 'phase' } }] })),
    { name: "complete broad string dispatcher", code: dispatch(), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "grouped labels share one terminal body", code: dispatch(SWITCH_BODY.replace('case "start":','case "start":case "retry":')), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "default before another case retains native matching", code: dispatch('switch(command){default:return {phase:"complete"};case "start":return {phase:"queued",ticket:"t"};}'), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "empty default shares next terminating case", code: dispatch('switch(command){case "start":return {phase:"queued",ticket:"t"};default:case "finish":return {phase:"complete"};}'), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "number dispatcher retains finite return tags", code: dispatch(SWITCH_BODY.replace('case "start"','case 1'),'number'), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "throwing case does not invent a result variant", code: dispatch(SWITCH_BODY.replace('default:', 'case "fail":throw Error();default:')), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "sole nested blocks retain flat terminal evidence", code: dispatch(SWITCH_BODY.replace('return { phase: "queued", ticket: "t" };','{{return {phase:"queued",ticket:"t"};}}')), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "async named dispatcher keeps own output relation", code:'type Job='+JOB_SHAPE+';async '+dispatch(SWITCH_BODY,'string','Promise<Job>'), errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "shared alias reports once across switch producers", code:'type Job='+JOB_SHAPE+';'+dispatch(SWITCH_BODY,'string','Job')+dispatch(SWITCH_BODY,'string','Job').replace('function job','function other'),errors:[{messageId:"preferProducedVariants",data:{tag:"phase"}}] },
    { name: "legacy alias advisory retains switch precedence", code:'type Result={ok:boolean;data?:string;error?:string};function load(command:string):Result{switch(command){case "start":return {ok:true,data:"x"};default:return{ok:false,error:"e"};}}',errors:[{messageId:"preferDiscriminatedUnion"}] },
    { name: "arbitrary domain tags and payloads on aliases", code: `type Job = ${JOB_SHAPE}; ${producer(JOB_BODY, 'Job')}`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' }, type: 'TSTypeAliasDeclaration' }] },
    { name: "arbitrary domain tags and payloads on interfaces", code: `interface Job ${JOB_SHAPE} ${producer(JOB_BODY, 'Job')}`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' }, type: 'TSInterfaceDeclaration' }] },
    { name: "inline return annotation", code: producer(), errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' }, type: 'TSTypeAnnotation' }] },
    { name: "shared metadata stays on every branch", code: producer('if (n) return { phase: "queued", id: "a", ticket: "t" }; return { phase: "complete", id: "b" };', '{ phase: "queued" | "complete"; id: string; ticket?: string }'), errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "async inline Promise boundary", code: `async function job(n: boolean): Promise<${JOB_SHAPE}> { ${JOB_BODY} }`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "async named Promise boundary", code: `type Job = ${JOB_SHAPE}; async function job(n: boolean): Promise<Job> { ${JOB_BODY} }`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "three distinct variants in conditional expression", code: 'const shape = (n: number): { form: "circle" | "rectangle" | "point"; radius?: number; width?: number; height?: number } => n === 1 ? { form: "circle", radius: 2 } : n === 2 ? { form: "rectangle", width: 3, height: 4 } : { form: "point" };', errors: [{ messageId: 'preferProducedVariants', data: { tag: 'form' } }] },
    { name: "function expression branches", code: `const factory = function(n: boolean): ${JOB_SHAPE} { if (n) { return { phase: "queued", ticket: "t" }; } else { return { phase: "complete" }; } };`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "object method producer", code: `const factory = { job(n: boolean): ${JOB_SHAPE} { ${JOB_BODY} } };`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "class method producer", code: `class Factory { job(n: boolean): ${JOB_SHAPE} { ${JOB_BODY} } }`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "numeric finite tags", code: 'function message(n: boolean): { opcode: 1 | 2; bytes?: string } { if (n) return { opcode: 1, bytes: "x" }; return { opcode: 2 }; }', errors: [{ messageId: 'preferProducedVariants', data: { tag: 'opcode' } }] },
    { name: "boolean arbitrary tags without name inference", code: 'function job(n: boolean): { cached: boolean; revision?: string } { if (n) return { cached: true, revision: "v1" }; return { cached: false }; }', errors: [{ messageId: 'preferProducedVariants', data: { tag: 'cached' } }] },
    { name: "quoted keys and readonly contracts", code: 'function job(n: boolean): { readonly "phase": "queued" | "complete"; readonly ticket?: string } { if (n) return { "phase": "queued", "ticket": "t" }; return { phase: "complete" }; }', errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "unrelated nested functions and throwing paths", code: producer(`function nested() { return cached; } if (other) throw new Error(); ${JOB_BODY}`), errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "same tag can have several consistent return sites", code: producer('if (n) return { phase: "queued", ticket: "t" }; if (other) return { phase: "queued", ticket: "u" }; return { phase: "complete" };'), errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "value-space declaration does not hide a type-space alias", code: `type Job = ${JOB_SHAPE}; function scope() { const Job = 1; ${producer(JOB_BODY, 'Job')} }`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' }, line: 1, column: 1 }] },
    { name: "shared contract reports once across repeated producers", code: `type Job = ${JOB_SHAPE}; ${producer(JOB_BODY, 'Job')} function second(n: boolean): Job { ${JOB_BODY} }`, errors: [{ messageId: 'preferProducedVariants', data: { tag: 'phase' } }] },
    { name: "legacy result diagnostic takes precedence on named contract", code: 'type Result = { ok: boolean; data?: string; error?: string }; function load(n: boolean): Result { if (n) return { ok: true, data: "x" }; return { ok: false, error: "e" }; }', errors: [{ messageId: 'preferDiscriminatedUnion' }] },
    { name: "legacy precedence is independent of alias declaration order", code: 'function load(n: boolean): Result { if (n) return { ok: true, data: "x" }; return { ok: false, error: "e" }; } type Result = { ok: boolean; data?: string; error?: string };', errors: [{ messageId: 'preferDiscriminatedUnion' }] },
    { name: "legacy precedence is independent of interface declaration order", code: 'function load(n: boolean): Result { if (n) return { ok: true, data: "x" }; return { ok: false, error: "e" }; } interface Result { ok: boolean; data?: string; error?: string }', errors: [{ messageId: 'preferDiscriminatedUnion' }] },
    { name: "legacy result diagnostic takes precedence on inline contract", code: 'function load(n: boolean): { ok: boolean; data?: string; error?: string } { if (n) return { ok: true, data: "x" }; return { ok: false, error: "e" }; }', errors: [{ messageId: 'preferDiscriminatedUnion' }] },
  ],
});
