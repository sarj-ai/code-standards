import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";
import ts from "typescript";

import rule, { NO_INVALID_TYPED_MUTATION_DOCUMENTATION } from "../../src/rules/no-invalid-typed-mutation.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser, parserOptions: {
  projectService: { allowDefaultProject: ["*.ts*"] }, tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
} } });
const COUNTER = 'const counter: { count: number } = { count: 1 };';

TESTER.run("no-invalid-typed-mutation", rule, {
  valid: [
    { name: "public compatible write", code: NO_INVALID_TYPED_MUTATION_DOCUMENTATION.examples[0].files[0].source },
    ...[
      ["compatible Reflect.set", 'Reflect.set(counter, "count", 2);'],
      ["compatible Object descriptor", 'Object.defineProperty(counter, "count", { value: 2, writable: true });'],
      ["compatible Reflect descriptor", 'Reflect.defineProperty(counter, "count", { value: 2 });'],
      ["extension fields have no previous contract", 'Object.assign(counter, { other: "x" });'],
      ["later assign source can restore legal state", 'Object.assign(counter, { count: "temporary" }, { count: 2 });'],
      ["spread can replace visible key", 'Object.assign(counter, { count: "bad", ...other });'],
      ["aliased source is not enumerability proof", 'const patch = { count: "bad" }; Object.assign(counter, patch);'],
      ["source getter has independent semantics", 'Object.assign(counter, { get count() { return "bad"; } });'],
      ["method source is outside plain data patches", 'Object.assign(counter, { count() { return "bad"; } });'],
      ["duplicate key can replace visible value", 'Object.assign(counter, { count: "bad", count: 2 });'],
      ["dynamic key is unknown", 'Object.assign(counter, { [key]: "bad" });'],
      ["Reflect receiver writes elsewhere", 'Reflect.set(counter, "count", "bad", receiver);'],
      ["dynamic Reflect key is unknown", 'Reflect.set(counter, key, "bad");'],
      ["descriptor alias is opaque", 'Object.defineProperty(counter, "count", descriptor);'],
      ["descriptor getter has separate semantics", 'Object.defineProperty(counter, "count", { get() { return "bad"; } });'],
      ["mixed descriptor is rejected before write", 'Object.defineProperty(counter, "count", { value: "bad", set(v: unknown) {} });'],
      ["descriptor spread can replace value", 'Object.defineProperty(counter, "count", { value: "bad", ...descriptor });'],
      ["inherited descriptor getter rejects the write", 'Object.prototype.get = () => 1; Object.defineProperty(counter, "count", { value: "bad" });'],
      ["computed prototype mutation invalidates Reflect descriptors too", 'globalThis["Object"]["prototype"]["get"] = () => 1; Reflect.defineProperty(counter, "count", { value: "bad" });'],
      ["reflective prototype mutation can change descriptor conversion", 'Reflect.set(Object.prototype, "get", () => 1); Reflect.defineProperty(counter, "count", { value: "bad" });'],
      ["escaped prototype can acquire inherited descriptor fields", 'configure(Object.prototype); Object.defineProperty(counter, "count", { value: "bad" });'],
      ["any source belongs to existing unsafe controls", 'declare const value: any; Object.assign(counter, { count: value });'],
      ["unknown source requires existing validation", 'declare const value: unknown; Object.assign(counter, { count: value });'],
      ["never source cannot complete write", 'declare const value: never; Object.assign(counter, { count: value });'],
      ["API alias does not prove native identity", 'const assign = Object.assign; assign(counter, { count: "bad" });'],
      ["later native replacement invalidates identity", 'Object.assign(counter, { count: "adapter" }); Object.assign = adapter;'],
      ["whole namespace replacement invalidates identity", 'Object = adapter; Object.assign(counter, { count: "adapter" });'],
      ["dynamic native property write invalidates identity", 'Object[key] = adapter; Object.assign(counter, { count: "adapter" });'],
      ["reflective native replacement invalidates identity", 'Reflect.set(Object, "assign", adapter); Object.assign(counter, { count: "adapter" });'],
      ["bulk descriptor native replacement invalidates identity", 'Object.defineProperties(Reflect, { set: { value: adapter } }); Reflect.set(counter, "count", "adapter");'],
    ].map(([name, code]) => ({ name, code: `${COUNTER} ${code}` })),
    ...[
      ["inferred target is deliberately excluded", 'const counter = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["fresh construction has no existing contract", 'Object.assign({}, { count: "bad" });'],
      ["member target is not traced", 'declare const holder: { counter: { count: number } }; Object.assign(holder.counter, { count: "bad" });'],
      ["compatible readonly value is not an incompatible write", 'const counter: { readonly count: number } = { count: 1 }; Object.assign(counter, { count: 2 });'],
      ["compatible mapped readonly value remains outside rule", 'const counter: Readonly<{ count: number }> = { count: 1 }; Object.assign(counter, { count: 2 });'],
      ["accessor write type can differ from read type", 'class Counter { get count(): number { return 1; } set count(value: string | number) {} } const counter: Counter = new Counter(); Reflect.set(counter, "count", "accepted");'],
      ["method overloads are not data properties", 'interface Counter { count(value: number): number; count(value: string): string; } declare const counter: Counter; Object.assign(counter, { count: false });'],
      ["overloaded function-valued property", 'interface Overload { (v: number): number; (v: string): string; } declare const counter: { count: Overload }; Object.assign(counter, { count: false });'],
      ["open dictionary", 'const counter: { count: number; [key: string]: number } = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["any target", 'declare const counter: any; Object.assign(counter, { count: "bad" });'],
      ["unknown target", 'declare const counter: unknown; Reflect.set(counter, "count", "bad");'],
      ["never target", 'declare const counter: never; Object.assign(counter, { count: "bad" });'],
      ["unknown-valued field intentionally accepts value", 'declare const counter: { count: unknown }; Object.assign(counter, { count: "valid" });'],
      ["unresolved generic target", 'function patch<T extends { count: number }>(counter: T) { Object.assign(counter, { count: "bad" }); }'],
      ["unresolved generic field", 'function patch<T>(counter: { count: T }) { Object.assign(counter, { count: "bad" }); }'],
      ["declared union can model intentional transition", 'declare const counter: { kind: "number"; count: number } | { kind: "text"; count: string }; if (counter.kind === "number") Object.assign(counter, { kind: "text", count: "valid transition" });'],
      ["intersection contract is not complete locally", 'declare const counter: { count: number } & Metadata; Object.assign(counter, { count: "bad" });'],
      ["Object scope shadow", 'function patch(Object: { assign(target: object, source: object): void }) { const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "adapter" }); }'],
      ["Reflect scope shadow", 'const Reflect = { set: (target: object, key: string, value: unknown) => true }; const counter: { count: number } = { count: 1 }; Reflect.set(counter, "count", "adapter");'],
      ["local overload augmentation", 'interface ObjectConstructor { assign(target: { count: number }, source: { count: string }): void; } const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "adapter" });'],
    ].map(([name, code]) => ({ name, code })),
    ...[
      ["parameter might be a coercing accessor", 'function patch(counter: { count: number }) { Object.assign(counter, { count: "accepted by runtime setter" }); }'],
      ["ambient declarations do not prove data storage", 'declare const counter: { count: number }; Object.assign(counter, { count: "adapter" });'],
      ["visible initializer setter preserves numeric contract", 'let stored = 1; const counter: { count: number } = { get count() { return stored; }, set count(value: unknown) { stored = Number(value); } }; Object.assign(counter, { count: "2" });'],
      ["structural annotation hides class accessor", 'class Coercing { get count(): number { return 1; } set count(value: unknown) {} } const counter: { count: number } = new Coercing(); Object.assign(counter, { count: "2" });'],
      ["proxy set trap may coerce writes", 'const counter: { count: number } = new Proxy({ count: 1 }, { set(target, key, value) { target.count = Number(value); return true; } }); Object.assign(counter, { count: "2" });'],
      ["factory or Object.create may install accessors", 'const counter: { count: number } = Object.create(null, { count: { get() { return 1; }, set(value: unknown) {} } }); Object.assign(counter, { count: "2" });'],
      ["initializer spread could supply accessors", 'const counter: { count: number } = { ...source }; Object.assign(counter, { count: "2" });'],
      ["prototype setter may handle missing own field", 'const counter: { count?: number } = { __proto__: adapter }; Object.assign(counter, { count: "2" });'],
      ["missing optional own field has unknown inherited behavior", 'const counter: { count?: number } = {}; Object.assign(counter, { count: "2" });'],
      ["explicitly exported target escapes ownership", 'export const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "2" });'],
      ["later export escapes ownership", 'const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "2" }); export { counter };'],
      ["alias escapes ownership", 'const counter: { count: number } = { count: 1 }; const alias = counter; Object.assign(counter, { count: "2" });'],
      ["opaque helper can replace descriptors", 'const counter: { count: number } = { count: 1 }; installSetter(counter); Object.assign(counter, { count: "2" });'],
      ["nested capture can escape descriptors", 'const counter: { count: number } = { count: 1 }; const callback = () => counter.count; Object.assign(counter, { count: "2" });'],
      ["method call can mutate through this", 'const counter: { count: number; install(): void } = { count: 1, install: function() {} }; counter.install(); Object.assign(counter, { count: "2" });'],
      ["returned assign value creates alias", 'const counter: { count: number } = { count: 1 }; const alias = Object.assign(counter, { count: "2" });'],
      ["opaque descriptor conversion loses storage proof", 'const counter: { count: number } = { count: 1 }; Object.defineProperty(counter, "count", { get() { return 1; }, set(value: unknown) {} }); Object.assign(counter, { count: "2" });'],
      ["deleting an own field loses local storage proof", 'const counter: { count?: number } = { count: 1 }; delete counter.count; Object.assign(counter, { count: "2" });'],
      ["optional delete loses local storage proof", 'const counter: { count?: number } = { count: 1 }; delete counter?.count; Object.assign(counter, { count: "2" });'],
      ["erased wrappers cannot conceal deletion", 'const counter: { count?: number } = { count: 1 }; delete (counter.count as number | undefined); Object.assign(counter, { count: "2" });'],
      ["deleted field may use an inherited coercing setter", 'let stored = 1; Object.defineProperty(Object.prototype, "count", { get() { return stored; }, set(value: unknown) { stored = Number(value); }, configurable: true }); const counter: { count?: number } = { count: 1 }; delete counter.count; Object.assign(counter, { count: "2" });'],
      ["a locked field makes later Reflect writes fail harmlessly", 'const counter: { count: number } = { count: 1 }; Object.defineProperty(counter, "count", { value: 2, writable: false }); Reflect.set(counter, "count", "ignored");'],
      ["a non-configurable field can reject a later descriptor", 'const counter: { count: number } = { count: 1 }; Object.defineProperty(counter, "count", { value: 2, configurable: false }); Reflect.defineProperty(counter, "count", { value: "ignored", configurable: true });'],
      ["dynamic writability cannot establish effective later writes", 'const counter: { count: number } = { count: 1 }; Object.defineProperty(counter, "count", { value: 2, writable: flag }); Reflect.set(counter, "count", "ignored");'],
      ["escaping Object allows method replacement", 'const counter: { count: number } = { count: 1 }; configure(Object); Object.assign(counter, { count: "adapter" });'],
      ["aliasing Object allows method replacement", 'const Native = Object; Native.assign = adapter; const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "adapter" });'],
      ["escaping Reflect allows method replacement", 'const counter: { count: number } = { count: 1 }; configure(Reflect); Reflect.set(counter, "count", "adapter");'],
      ["canonical global namespace aliases escape too", 'const Native = globalThis.Object; Native.assign = adapter; const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "adapter" });'],
      ["global receiver aliases can replace both namespaces", 'const globals = globalThis; globals.Object.assign = adapter; const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "adapter" });'],
      ["passing the global receiver can replace both namespaces", 'configure(globalThis); const counter: { count: number } = { count: 1 }; Reflect.set(counter, "count", "adapter");'],
      ["freeze operation loses mutable storage proof", 'const counter: { count: number } = { count: 1 }; Object.freeze(counter); Object.assign(counter, { count: "2" });'],
      ["nested generic source is unresolved", 'function patch<T>(value: T) { const counter: { count: { value: number } } = { count: { value: 1 } }; Object.assign(counter, { count: { value } }); }'],
      ["generic callable source is unresolved", 'function patch<T>(value: T) { const counter: { count: () => number } = { count: () => 1 }; Object.assign(counter, { count: () => value }); }'],
      ["generic array source is unresolved", 'function patch<T>(items: T[]) { const counter: { count: number[] } = { count: [] }; Object.assign(counter, { count: items }); }'],
      ["generic array contract is unresolved", 'function patch<T>() { const counter: { count: T[] } = { count: [] }; Object.assign(counter, { count: ["2"] }); }'],
      ["canonical global method replacement loses native identity", 'globalThis.Object.assign = adapter; const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "2" });'],
      ["canonical global reflective replacement loses native identity", 'Reflect.set(globalThis.Object, "assign", adapter); const counter: { count: number } = { count: 1 }; Object.assign(counter, { count: "2" });'],
    ].map(([name, code]) => ({ name, code })),
    { name: "exact-code suppression", code: `${COUNTER}\n// eslint-disable-next-line @rule-tester/no-invalid-typed-mutation -- external adapter owns conversion\nObject.assign(counter, { count: "external" });` },
    { name: "generated ownership", filename: 'counter.generated.ts', code: `${COUNTER} Object.assign(counter, { count: "bad" });` },
  ],
  invalid: [
    { name: "public incompatible write", code: NO_INVALID_TYPED_MUTATION_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "incompatibleWrite" }] },
    ...[
      ["plain compatible descriptors retain writable storage", `${COUNTER} Object.defineProperty(counter, "count", { value: 2, writable: true, configurable: true }); Reflect.set(counter, "count", "bad");`],
      ["typeof namespace does not escape API ownership", `${COUNTER} if (typeof Object === "function") Object.assign(counter, { count: "bad" });`],
      ["ordinary native member receiver does not escape API ownership", `${COUNTER} Object.keys({ x: 1 }); Object.assign(counter, { count: "bad" });`],
      ["ordinary prototype property read does not mutate descriptors", `${COUNTER} const tag = Object.prototype.toString; Reflect.defineProperty(counter, "count", { value: "bad" });`],
      ["readonly annotation does not freeze local data", 'const counter: { readonly count: number } = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["mapped readonly annotation does not freeze local data", 'const counter: Readonly<{ count: number }> = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["incompatible concrete arrays preserve element contracts", 'const counter: { count: number[] } = { count: [] }; Object.assign(counter, { count: ["bad"] });'],
      ["canonical global API retains identity", `${COUNTER} globalThis.Object.assign(counter, { count: "bad" });`],
      ["Reflect.set", `${COUNTER} Reflect.set(counter, "count", "bad");`],
      ["Object descriptor", `${COUNTER} Object.defineProperty(counter, "count", { value: "bad", writable: true });`],
      ["Reflect descriptor", `${COUNTER} Reflect.defineProperty(counter, "count", { value: "bad" });`],
      ["static computed API and field", `${COUNTER} Object["assign"](counter, { ["count"]: "bad" });`],
      ["static no-substitution key", `${COUNTER} Reflect.set(counter, \`count\`, "bad");`],
      ["named interface", 'interface Counter { count: number } const counter: Counter = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["class field", 'class Counter { count: number = 1; } const counter: Counter = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["union field requires compatible value", 'const counter: { count: number | null } = { count: 1 }; Object.assign(counter, { count: "bad" });'],
      ["raw primitive cannot bypass a branded field", 'type UserId = string & { readonly user: unique symbol }; declare const owner: UserId; const record: { owner: UserId } = { owner }; Object.assign(record, { owner: "raw" });'],
      ["one finding per mutation call", 'const target: { count: number; flag: boolean } = { count: 1, flag: true }; Object.assign(target, { count: "bad", flag: "bad" });'],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "incompatibleWrite" as const }] })),
    { name: "real contracts in tests remain checked", filename: 'counter.test.ts', code: `${COUNTER} Object.assign(counter, { count: "bad" });`, errors: [{ messageId: "incompatibleWrite" }] },
  ],
});

const SYNTAX_TESTER = new RuleTester({ languageOptions: { parser } });
SYNTAX_TESTER.run("no-invalid-typed-mutation without type information", rule, {
  valid: [`${COUNTER} Object.assign(counter, { count: "bad" });`], invalid: [],
});

// Each fixture supplies a native TSProgram so both optional-property policies are tested.
const POLICY_TESTER = new RuleTester({ languageOptions: { parser } });
const OMITTED_UNDEFINED = 'const counter: { count?: number } = { count: 1 }; Object.assign(counter, { count: undefined });';
const EXPLICIT_UNDEFINED = 'const counter: { count?: number | undefined } = { count: 1 }; Object.assign(counter, { count: undefined });';

POLICY_TESTER.run("no-invalid-typed-mutation exact optional policy", rule, {
  valid: [
    optionalCase("non-exact policy permits explicit undefined", OMITTED_UNDEFINED, false),
    optionalCase("authored undefined remains a valid exact write", EXPLICIT_UNDEFINED, true),
    optionalCase("mapped write type must not reuse the original field annotation", 'type ToText<T> = { [K in keyof T]?: string }; const counter: ToText<{ count?: number }> = { count: "one" }; Object.assign(counter, { count: "two" });', true),
    optionalCase("generic instantiation preserves an explicitly allowed undefined", 'type Box<T> = { count?: T }; const counter: Box<number | undefined> = { count: 1 }; Object.assign(counter, { count: undefined });', true),
  ],
  invalid: [{ ...optionalCase("exact policy forbids an unlisted explicit undefined", OMITTED_UNDEFINED, true), errors: [{ messageId: "incompatibleWrite" }] }],
});

function optionalCase(name: string, code: string, exactOptionalPropertyTypes: boolean) {
  const filename = join(import.meta.dirname, "..", "fixtures", "optional-policy.ts");
  const options: ts.CompilerOptions = { noEmit: true, strict: true, exactOptionalPropertyTypes, target: ts.ScriptTarget.ES2022, types: [] };
  const host = ts.createCompilerHost(options);
  const original = host.getSourceFile.bind(host);
  host.getSourceFile = (path, version, onError, create) => path === filename ? ts.createSourceFile(path, code, version, true) : original(path, version, onError, create);
  const program = ts.createProgram([filename], options, host);
  return { name, code, filename, languageOptions: { parserOptions: { programs: [program] } } };
}
