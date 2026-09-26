import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import rule, { STEPDOWN_DOCUMENTATION } from "../../src/rules/stepdown.js";
import { ErasedPrivate, ReorderedPrivate } from "../fixtures/private-member-reflection.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

const DEEP_CYCLE_SIZE = 12_000;
const DEEP_CYCLE = Array.from(
  { length: DEEP_CYCLE_SIZE },
  (_unused, index) => `function f${index}() { return f${(index + 1) % DEEP_CYCLE_SIZE}(); }`,
).join("\n");
const DEEP_CHAIN_SIZE = 14;
const DEEP_CHAIN = `class Service { ${Array.from(
  { length: DEEP_CHAIN_SIZE },
  (_unused, offset) => {
    const index = DEEP_CHAIN_SIZE - offset - 1;
    return index === DEEP_CHAIN_SIZE - 1
      ? `private helper${index}() { return 1; }`
      : `private helper${index}() { return this.helper${index + 1}(); }`;
  },
).join(" ")} }`;

RULE_TESTER.run("stepdown", rule, {
  valid: [
    { name: "accepts the documented caller-first order", code: STEPDOWN_DOCUMENTATION.examples[0].files[0].source },
    { name: "handles a deep cyclic graph without recursive stack overflow", code: DEEP_CYCLE },
    {
      name: "allows a module helper below its sole caller",
      code: "function run() { return load(); }\nfunction load() { return 1; }",
    },
    {
      name: "allows an exported helper",
      code: "export function load() { return 1; }\nfunction run() { return load(); }",
    },
    {
      name: "allows helpers with multiple callers",
      code: "function load() { return 1; }\nfunction first() { return load(); }\nfunction second() { return load(); }",
    },
    {
      name: "allows callback references",
      code: "function normalize(v: string) { return v.trim(); }\nfunction run(xs: string[]) { return xs.map(normalize); }",
    },
    {
      name: "allows references from nested callbacks",
      code: "function load() { return 1; }\nfunction run(xs: number[]) { return xs.map(() => load()); }",
    },
    {
      name: "allows a helper below its arrow-function caller",
      code: "const run = () => load();\nconst load = () => 1;",
    },
    {
      name: "does not reason about a reassigned function binding",
      code: "let load = () => 1;\nload = () => 2;\nfunction run() { return load(); }",
    },
    {
      name: "allows recursive call-graph cycles",
      code: "function odd(n: number): boolean { return n > 0 && even(n - 1); }\nfunction even(n: number): boolean { return n === 0 || odd(n - 1); }",
    },
    {
      name: "allows a cycle through an exported caller",
      code: "function load() { return run(); }\nexport function run() { return load(); }",
    },
    {
      name: "allows overload declarations",
      code: "function load(value: string): string;\nfunction load(value: number): number;\nfunction load(value: string | number) { return value; }\nfunction run() { return load(1); }",
    },
    {
      name: "does not move a helper across an initialized class field",
      code: "class Service { private load() { return 1; } state = register(this); private run() { return this.load(); } }",
    },
    {
      name: "does not move a helper across a static initialization block",
      code: "class Service { private load() { return 1; } static { register(Service); } private run() { return this.load(); } }",
    },
    {
      name: "does not move a helper below a decorated caller",
      code: "class Service { private load() { return 1; } @register private run() { return this.load(); } }",
    },
    {
      name: "allows public and protected methods",
      code: "class Service { public load() { return 1; } protected parse() { return 2; } run() { return this.load() + this.parse(); } }",
    },
    {
      name: "allows a private method referenced as a value",
      code: "class Service { private normalize(v: string) { return v.trim(); } run(xs: string[]) { return xs.map(this.normalize); } }",
    },
    {
      name: "allows a private method referenced by a class field",
      code: "class Service { private normalize(v: string) { return v.trim(); } handler = this.normalize; run(v: string) { return this.normalize(v); } }",
    },
    {
      name: "does not suggest reordering a cycle through a public method",
      code: "class Service { private load() { return this.run(); } public run() { return this.load(); } }",
    },
    {
      name: "does not suggest reordering a cycle through a protected method",
      code: "class Service { private load() { return this.run(); } protected run() { return this.load(); } }",
    },
    {
      name: "does not move a const helper across eager execution",
      code: "const load = () => 1; run(); function run() { return load(); }",
    },
    {
      name: "does not move a const helper across an initializer",
      code: "const load = () => 1; const result = run(); function run() { return load(); }",
    },
    {
      name: "does not move an individual helper from a multi-declarator statement",
      code: "const load = () => 1, other = run(); function run() { return load(); }",
    },
    {
      name: "pins an escaped local callable alias",
      code: "function load() { return 1; } function run() { const call = load; consume(call); return call(); }",
    },
    {
      name: "pins a callable alias used by a nested callback",
      code: "function load() { return 1; } function run() { const call = load; return () => call(); }",
    },
    {
      name: "pins a mutable callable alias",
      code: "function load() { return 1; } function run() { let call = load; return call(); }",
    },
    {
      name: "pins a class receiver that can be reassigned",
      code: "let Service = class { private static load() { return 1; } static run() { return Service.load(); } };",
    },
    {
      name: "pins an escaped method alias",
      code: "class Service { private load() { return 1; } run() { const call = this.load; consume(call); return call(); } }",
    },
    {
      name: "pins a dynamic computed receiver reference",
      code: "class Service { private load() { return 1; } run(key: string) { return this.load() + this[key](); } }",
    },
    {
      name: "pins a dynamic computed reference through a mutable receiver alias",
      code: "class Service { private load() { return 1; } run() { return this.load(); } other(key: string) { let that = this; return that[key](); } }",
    },
    {
      name: "pins destructuring through an uncertain receiver",
      code: "class Service { private load() { return 1; } run() { return this.load(); } other() { let that = this; const { 'load': call } = that; return call(); } }",
    },
    {
      name: "pins a dynamic computed reference through a default receiver alias",
      code: "class Service { private load() { return 1; } run() { return this.load(); } other(key: string, that = this) { return that[key](); } }",
    },
    {
      name: "includes quoted method names when identifying cycles",
      code: "class Service { private load() { return this.hop(); } run() { return this.load(); } 'hop'() { return this.run(); } }",
    },
    {
      name: "includes overloaded method implementations when identifying cycles",
      code: "class Service { private load() { return this.hop(); } run() { return this.load(); } hop(): number; hop() { return this.run(); } }",
    },
    {
      name: "pins callers whose computed method identity is unknown",
      code: "class Service { private load() { return 1; } run() { return this.load(); } ['other' + suffix]() { return this.load(); } }",
    },
    {
      name: "pins a quoted destructuring reference",
      code: "class Service { private load() { return 1; } run() { const { 'load': call } = this; return this.load() + call(); } }",
    },
    {
      name: "pins a computed destructuring reference",
      code: "class Service { private load() { return 1; } run(key: string) { const { [key]: call } = this; return this.load() + call(); } }",
    },
    {
      name: "pins destructuring in a parameter default",
      code: "class Service { private load() { return 1; } run({ 'load': call } = this) { return this.load() + call(); } }",
    },
    {
      name: "pins a destructuring assignment",
      code: "class Service { private load() { return 1; } run() { let call; ({ 'load': call } = this); return this.load() + call(); } }",
    },
    {
      name: "pins an escaping receiver alias",
      code: "class Service { private load() { return 1; } run() { const self = this; consume(self); return this.load(); } }",
    },
    {
      name: "pins a receiver alias used in a nested function",
      code: "class Service { private load() { return 1; } run() { const self = this; const callback = () => self.load(); return this.load(); } }",
    },
    {
      name: "keeps mixed static and instance call cycles intact",
      code: "class Service { private load() { return Service.run(); } static run(value: Service) { return value.load(); } }",
    },
    {
      name: "pins a callable referenced inside a nested class",
      code: "class Service { private load() { return 1; } run() { class Nested { run() { return this.load(); } } return this.load(); } }",
    },
    {
      name: "allows a private method destructured from this",
      code: "class Service { private load() { return 1; } private run() { const { load } = this; return this.load() + load.call(this); } }",
    },
    {
      name: "allows wrapped and rest destructuring from this",
      code: "class Service { private load() { return 1; } private run() { const { load, ...rest } = this as Service; return this.load() + load.call(rest); } }",
    },
    {
      name: "allows a private method referenced through a default this alias",
      code: "class Service { private load() { return 1; } private run(self = this) { return this.load() + self.load(); } }",
    },
    {
      name: "allows another instance to reference the same private method",
      code: "class Service { private load() { return 1; } private run(other: Service) { return this.load() + other.load(); } }",
    },
    {
      name: "allows another instance reference from a class field",
      code: "class Service { private load() { return 1; } private run() { return this.load(); } other!: Service; handler = () => this.other.load(); }",
    },
    {
      name: "allows a private static helper referenced by a method decorator",
      code: "class Service { private static load() { return 1; } @deco(Service.load) private run() { return Service.load(); } }",
    },
    {
      name: "pins a private helper referenced while evaluating a parameter decorator",
      code: "class Service { private static load() { return 1; } private run(@deco(Service.load()) value: string) { return value; } }",
    },
    {
      name: "allows a private method called through a computed property",
      code: "class Service { private load() { return 1; } run() { return this['load'](); } }",
    },
    {
      name: "allows test files",
      filename: "/repo/src/service.test.ts",
      code: "function helper() { return 1; }\nfunction testThing() { return helper(); }",
    },
    {
      name: "allows generated files",
      filename: "/repo/src/generated/service.ts",
      code: "function helper() { return 1; }\nfunction run() { return helper(); }",
    },
    {
      name: "allows an external bracket reference to a private method",
      code: "class Service { private load() { return 1; } private run() { return this.load(); } }\nnew Service()['load']();",
    },
    {
      name: "does not confuse a shadow of the class name with a static call",
      code: "class Service { private static load() { return 1; } private run(Service: { load(): number }) { return Service.load(); } }",
    },
  ],
  invalid: [
    { name: "reports the documented helper-first order", code: STEPDOWN_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }] },
    {
      name: "counts a stable local receiver alias",
      code: "class Service { private load() { return 1; } run() { const self = this; return this.load() + self.load(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "keeps static and instance method identities separate",
      code: "class Service { private load() { return 1; } static load() { return 2; } run() { return this.load(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "resolves the immutable internal class name when its outer binding is reassigned",
      code: "class Service { private static load() { return 1; } static run() { return Service.load(); } } Service = replacement;",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "keeps static and instance callers separate",
      code: "class Service { private static load() { return 1; } static run() { return this.load(); } run() { return 2; } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "counts a local nonescaping callable alias chain",
      code: "function load() { return 1; } function run() { const first = load; const second = first; return second(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "counts a local nonescaping method alias",
      code: "class Service { private load() { return 1; } run() { const call = this.load; return call(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "recognizes erased wrappers around callable definitions and calls",
      code: "const load = (() => 1) satisfies () => number; function run() { return (load as () => number)!(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "recognizes erased wrappers around a method receiver and callable",
      code: "class Service { private load() { return 1; } run() { return ((this as Service).load satisfies () => number)!(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "retains hoisted function movement across eager execution",
      code: "function load() { return 1; } run(); function run() { return load(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "keeps an overlapping deep dependency chain report-only instead of partially rewriting it",
      code: DEEP_CHAIN,
      output: null,
      errors: DEEP_CHAIN_SIZE - 1,
    },
    {
      name: "reports private helper ordering without rewriting reflected method order",
      code: "class Service { private load() { return 1; } public run() { return this.load(); } }",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "counts an overloaded implementation as the helper's sole caller",
      code: "function load() { return 1; }\nfunction get(x: string): string;\nfunction get(x: number): number;\nfunction get(x: unknown) { return String(load()) + String(x); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "get" } }],
    },
    {
      name: "includes a named default-export function as a caller",
      code: "function load() { return 1; }\nexport default function run() { return load(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "self recursion does not hide a module helper's sole external caller",
      code: "function walk(n: number): number { return n <= 0 ? 0 : walk(n - 1); }\nfunction run() { return walk(2); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "walk", caller: "run" } }],
    },
    {
      name: "self recursion does not hide a private method's sole external caller",
      code: "class Service { private walk(n: number): number { return n <= 0 ? 0 : this.walk(n - 1); } private run() { return this.walk(2); } }",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "walk", caller: "run" } }],
    },
    {
      name: "reports a module helper above its sole caller",
      code: "function load() { return 1; }\nfunction run() { return load(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports a const arrow helper above its sole arrow caller",
      code: "const load = () => 1;\nexport const run = () => load();",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "resolves a class expression through its outer const binding",
      code: "const Service = class { private static load() { return 1; } private static run() { return Service.load(); } };",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports a helper above an exported function caller",
      code: "function load() { return 1; }\nexport function run() { return load(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "does not mistake a source re-export for exporting the local helper",
      code: "function load() { return 1; }\nexport { load } from './remote.js';\nfunction run() { return load(); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports an explicitly private method above its sole private caller",
      code: "class Service {\n  private load() { return 1; }\n  private run() { return this.load(); }\n}",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports a hash-private method above its sole private caller",
      code: "class Service { #load() { return 1; } private run() { return this.#load(); } }",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "#load", caller: "run" } }],
    },
    {
      name: "reports a hash-private helper above a hash-private caller",
      code: "class Service { #load() { return 1; } #run() { return this.#load(); } }",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "#load", caller: "#run" } }],
    },
    {
      name: "reports a private static helper called through the class binding",
      code: "class Service { private static load() { return 1; } private static run() { return Service.load(); } }",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports a helper called by a parameter default",
      code: "class Service { private load() { return 1; } private run(value = this.load()) { return value; } }",
      output: null,
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
  ],
});

it("method reordering changes observable prototype key order", () => {
  expect(new ErasedPrivate().run()).toBe(new ReorderedPrivate().run());
  expect(Object.getOwnPropertyNames(ErasedPrivate.prototype)).toEqual(["constructor", "load", "run"]);
  expect(Object.getOwnPropertyNames(ReorderedPrivate.prototype)).toEqual(["constructor", "run", "load"]);
});
