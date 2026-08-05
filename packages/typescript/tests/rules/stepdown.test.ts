import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/stepdown.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({ languageOptions: { parser: tsParser } });

ruleTester.run("stepdown", rule, {
  valid: [
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
      name: "leaves public-before-private ordering to member-ordering",
      code: "class Service { private load() { return 1; } public run() { return this.load(); } }",
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
    {
      name: "self recursion does not hide a module helper's sole external caller",
      code: "function walk(n: number): number { return n <= 0 ? 0 : walk(n - 1); }\nfunction run() { return walk(2); }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "walk", caller: "run" } }],
    },
    {
      name: "self recursion does not hide a private method's sole external caller",
      code: "class Service { private walk(n: number): number { return n <= 0 ? 0 : this.walk(n - 1); } private run() { return this.walk(2); } }",
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
      code: "class Service { private load() { return 1; } private run() { return this.load(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports a hash-private method above its sole private caller",
      code: "class Service { #load() { return 1; } private run() { return this.#load(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "#load", caller: "run" } }],
    },
    {
      name: "reports a hash-private helper above a hash-private caller",
      code: "class Service { #load() { return 1; } #run() { return this.#load(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "#load", caller: "#run" } }],
    },
    {
      name: "reports a private static helper called through the class binding",
      code: "class Service { private static load() { return 1; } private static run() { return Service.load(); } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
    {
      name: "reports a helper called by a parameter default",
      code: "class Service { private load() { return 1; } private run(value = this.load()) { return value; } }",
      errors: [{ messageId: "helperAboveOnlyCaller", data: { helper: "load", caller: "run" } }],
    },
  ],
});
