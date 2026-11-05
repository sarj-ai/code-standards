// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { Linter } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import { RECOMMENDED_RULES, STRICT_RULES } from "../../src/index.js";
import rule from "../../src/rules/no-runtime-typeof.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });
const ERROR = { messageId: "runtimeTypeof" } as const;

RULE_TESTER.run("no-runtime-typeof", rule, {
  valid: [
    { name: "preserves an unwrapped script arguments probe", filename: "src/probe.js", languageOptions: { sourceType: "script" }, code: 'typeof arguments === "undefined";' },
    { name: "uses declared script mode over the CommonJS filename", filename: "src/probe.cjs", languageOptions: { sourceType: "script" }, code: 'typeof arguments === "undefined";' },
    { name: "preserves absent module arguments", filename: "src/probe.js", code: 'typeof arguments === "undefined";' },
    { name: "preserves absent arguments in a module arrow", filename: "src/probe.js", code: 'const probe = () => typeof arguments === "undefined";' },
    { name: "ignores body-only declarations in parameter initializers", filename: "src/probe.js", code: 'function probe(value = typeof Map === "undefined") { const Map = 1; return value; }' },
    { name: "ignores body-only declarations in nested parameter evaluation", filename: "src/probe.js", code: 'function probe(value = (() => typeof Map === "undefined")()) { const Map = 1; return value; }' },
    { name: "ignores arrow body declarations in parameter initializers", filename: "src/probe.js", code: 'const probe = (value = typeof Map === "undefined") => { const Map = 1; return value; };' },
    { name: "ignores expression body declarations in parameter initializers", filename: "src/probe.js", code: 'const probe = function (value = typeof Map === "undefined") { const Map = 1; return value; };' },
    { name: "does not let an erased parameter expose a body value", code: 'function probe<Map>(value = typeof Map === "undefined") { const Map = 1; return value; }' },
    { name: "preserves type-only queries", code: "declare const source: { id: string }; type Value = typeof source;" },
    { name: "preserves imported type-only queries", code: "type Module = typeof import('./source');" },
    { name: "accepts a discriminated contract", code: 'type Value = { kind: "text"; value: string } | { kind: "count"; value: number }; function read(value: Value) { return value.kind === "text" ? value.value : String(value.value); }' },
    { name: "accepts specific schema parsing", code: 'import { z } from "zod"; const InputSchema = z.object({ id: z.string() }); InputSchema.parse(raw);' },
    { name: "preserves an absent global equality probe", code: 'typeof document === "undefined";' },
    { name: "preserves a global inequality probe", code: 'typeof window !== "undefined";' },
    { name: "preserves reversed global probes", code: '"undefined" === typeof missingGlobal;' },
    { name: "preserves loose global probes", code: 'typeof document == "undefined"; "undefined" != typeof window;' },
    { name: "preserves a global beside an erased type alias", code: 'export {}; type window = number; typeof window === "undefined";' },
    { name: "preserves a global beside an erased interface", code: 'export {}; interface document { value: string } typeof document !== "undefined";' },
    { name: "preserves a global beside an erased type parameter", code: 'function probe<window>() { return typeof window === "undefined"; }' },
    { name: "preserves a global beside an empty namespace", code: 'export {}; namespace window {} typeof window === "undefined";' },
    { name: "preserves a global beside a type-only namespace", code: 'export {}; namespace window { export type Value = number; } typeof window === "undefined";' },
    { name: "preserves a global beside nested type-only namespaces", code: 'export {}; namespace window { export namespace Inner { export interface Value {} } } typeof window === "undefined";' },
    { name: "preserves an erased wrapper around the probe", code: '(typeof window as string) === "undefined";' },
    { name: "preserves erased wrappers around the global", code: 'typeof (window as unknown) === "undefined"; typeof (document satisfies unknown)! !== "undefined";' },
    { name: "preserves an erased wrapper around the literal", code: 'typeof window === ("undefined" as const);' },
    { name: "preserves reversed erased global probes", code: '("undefined" as const) != (typeof (window as unknown) satisfies string);' },
    { name: "ignores text containing the operator", code: 'const message = "typeof value === string"; // typeof value\n' },
    { name: "preserves generated source", code: '// @generated by schema-tool\nconst kind = typeof value;' },
    { name: "preserves a generated path", filename: "/repo/generated/client.ts", code: "const kind = typeof value;" },
    { name: "preserves vendored source", filename: "/repo/vendor/client.ts", code: "const kind = typeof value;" },
  ],
  invalid: [
    { name: "retains implicit function arguments", code: 'function probe() { return typeof arguments === "undefined"; }', errors: [ERROR] },
    { name: "retains implicit expression arguments", code: 'const probe = function () { return typeof arguments === "undefined"; };', errors: [ERROR] },
    { name: "retains arguments captured by an arrow", code: 'function probe() { return () => typeof arguments === "undefined"; }', errors: [ERROR] },
    { name: "retains arguments in a parameter initializer", code: 'function probe(value = typeof arguments === "undefined") { return value; }', errors: [ERROR] },
    { name: "retains implicit method arguments", code: 'const probe = { read() { return typeof arguments === "undefined"; } };', errors: [ERROR] },
    { name: "retains implicit CommonJS wrapper arguments", filename: "src/probe.cjs", languageOptions: { sourceType: "commonjs" }, code: 'typeof arguments === "undefined";', errors: [ERROR] },
    { name: "retains arguments beside an erased declaration", code: 'function probe() { type arguments = number; return typeof arguments === "undefined"; }', errors: [ERROR] },
    { name: "retains earlier parameter values", filename: "src/probe.js", code: 'function probe(Map = globalThis.Map, value = typeof Map === "undefined") { return value; }', errors: [ERROR] },
    { name: "retains outer values used in parameter initializers", filename: "src/probe.js", code: 'const Map = 1; function probe(value = typeof Map === "undefined") { const Map = 2; return value; }', errors: [ERROR] },
    { name: "retains body values inside the body", filename: "src/probe.js", code: 'function probe() { const Map = 1; return typeof Map === "undefined"; }', errors: [ERROR] },
    { name: "rejects ad hoc primitive parsing", code: 'function parse(value: unknown) { return typeof value === "string"; }', output: null, errors: [ERROR] },
    { name: "rejects object probing", code: 'function parse(value: unknown) { return typeof value === "object" && value !== null; }', errors: [ERROR] },
    { name: "rejects function dispatch without an explained exception", code: 'const next = typeof update === "function" ? update(previous) : update;', errors: [ERROR] },
    { name: "rejects standalone typeof", code: "const kind = typeof value;", errors: [ERROR] },
    { name: "rejects a runtime typeof inside a type assertion", code: "const kind = (typeof value) as string;", errors: [ERROR] },
    { name: "does not exempt a function named parser", code: 'function parseInput(value: unknown) { return typeof value === "number"; }', errors: [ERROR] },
    { name: "does not exempt explicit predicates", code: 'function isString(value: unknown): value is string { return typeof value === "string"; }', errors: [ERROR] },
    { name: "does not exempt schema callbacks by name", code: 'Schema.preprocess(value => typeof value === "string" ? value : "");', errors: [ERROR] },
    { name: "rejects a runtime check beside a type query", code: "type Value = typeof value; const kind = typeof value;", errors: [ERROR] },
    { name: "checks maintained tests", filename: "/repo/src/input.test.ts", code: 'test("text", () => expect(typeof result).toBe("string"));', errors: [ERROR] },
    { name: "checks JavaScript", filename: "/repo/src/input.js", code: "const kind = typeof value;", errors: [ERROR] },
    { name: "checks JSX expressions", filename: "/repo/src/input.tsx", code: "const view = <div>{typeof value}</div>;", errors: [ERROR] },
    { name: "checks dynamic type comparisons", code: "typeof value === expectedType;", errors: [ERROR] },
    { name: "checks switch discriminants", code: 'switch (typeof value) { case "string": break; }', errors: [ERROR] },
    { name: "does not mistake property checks for absent globals", code: 'typeof globalThis.document === "undefined";', errors: [ERROR] },
    { name: "does not exempt bound parameters", code: 'function check(value: unknown) { return typeof value === "undefined"; }', errors: [ERROR] },
    { name: "does not exempt a shadowed global", code: 'function check(document: unknown) { return typeof document === "undefined"; }', errors: [ERROR] },
    { name: "finds an outer value behind an erased type alias", code: 'function check(document: unknown) { { type document = string; return typeof document === "undefined"; } }', errors: [ERROR] },
    { name: "retains a value merged with an interface", code: 'export {}; interface window { value: string } class window {} typeof window === "undefined";', errors: [ERROR] },
    { name: "retains enum value bindings", code: 'export {}; enum window { one } typeof window === "undefined";', errors: [ERROR] },
    { name: "retains namespace value bindings", code: 'export {}; namespace window { export const value = 1; } typeof window === "undefined";', errors: [ERROR] },
    { name: "retains values merged with a type-only namespace", code: 'export {}; namespace window { export type Value = number; } namespace window { export const value = 1; } typeof window === "undefined";', errors: [ERROR] },
    { name: "retains ambient value members", code: 'export {}; namespace window { export declare const value: number; } typeof window === "undefined";', errors: [ERROR] },
    { name: "retains const-enum namespaces with configuration-dependent emission", code: 'export {}; namespace window { export const enum Value { one } } typeof window === "undefined";', errors: [ERROR] },
    { name: "finds an outer value behind a type-only namespace", code: 'export {}; namespace Outer { const window = {}; export namespace Inner { export namespace window { export type Value = number; } export const missing = typeof window === "undefined"; } }', errors: [ERROR] },
    { name: "retains values beside type parameters", code: 'function check<window>(window: unknown) { return typeof window === "undefined"; }', errors: [ERROR] },
    { name: "checks erased wrappers around bound probes", code: 'function check(window: unknown) { return (typeof (window as unknown) as string) === ("undefined" as const); }', errors: [ERROR] },
    { name: "does not exempt a standalone probe beside a type alias", code: 'export {}; type window = number; const kind = typeof window;', errors: [ERROR] },
    { name: "does not exempt imports", code: 'import { document } from "./local"; typeof document === "undefined";', errors: [ERROR] },
    { name: "does not exempt temporal dead zone bindings", code: 'typeof document === "undefined"; const document = {};', errors: [ERROR] },
    { name: "does not exempt a nonliteral undefined operand", code: "typeof document === undefined;", errors: [ERROR] },
    { name: "checks authored AI source", code: "// Generated by an AI assistant\nconst kind = typeof value;", errors: [ERROR] },
    { name: "reports each runtime expression", code: "const left = typeof first; const right = typeof second;", errors: [ERROR, ERROR] },
  ],
});

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule, { installedDependencyRoot: import.meta.dirname + "/../.." });
});

it("enforces the requested ban in both public presets", () => {
  expect(STRICT_RULES["@sarj/no-runtime-typeof"]).toBe("error");
  expect(RECOMMENDED_RULES["@sarj/no-runtime-typeof"]).toBe("error");
});

const INLINE_CONFIG = {
  files: ["**/*.ts"],
  languageOptions: { parser: tsParser },
  plugins: { "@sarj": { rules: { "no-runtime-typeof": rule } } },
  rules: { "@sarj/no-runtime-typeof": "error" },
} as const;

it("retains an exact-code local exception for a raw preprocessing contract", () => {
  const messages = new Linter().verify(
    '// eslint-disable-next-line @sarj/no-runtime-typeof -- This preprocessor inspects raw values before the caller schema establishes their contract.\nfunction inspect(value: unknown) { return typeof value === "object"; }',
    INLINE_CONFIG,
    { filename: "src/preprocess.ts" },
  );
  expect(messages).toEqual([]);
});

it("keeps an exception local to its annotated line", () => {
  const messages = new Linter().verify(
    '// eslint-disable-next-line @sarj/no-runtime-typeof -- This framework callback distinguishes a setter function from its boolean value.\nconst next = typeof update === "function" ? update(previous) : update;\nconst kind = typeof input;',
    INLINE_CONFIG,
    { filename: "src/setter.ts" },
  );
  expect(messages).toEqual([expect.objectContaining({ ruleId: "@sarj/no-runtime-typeof", line: 3, severity: 2 })]);
});

it("leaves malformed input to the native parser", () => {
  const messages = new Linter().verify("const value = typeof ;", INLINE_CONFIG, { filename: "src/input.ts" });
  expect(messages).toEqual([expect.objectContaining({ fatal: true, ruleId: null })]);
});
