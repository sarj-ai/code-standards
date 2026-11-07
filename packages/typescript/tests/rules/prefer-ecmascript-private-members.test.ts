import { expect, it } from "vitest";

import rule from "../../src/rules/prefer-ecmascript-private-members.js";
import { ErasedPrivate, RuntimePrivate } from "../fixtures/private-member-reflection.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

const RUNTIME_PRIVATE_EXAMPLE = "class Vault { #read() { return 1; } open() { return this.#read(); } }";
const TYPESCRIPT_PRIVATE_EXAMPLE = "class Vault { private read() { return 1; } open() { return this.read(); } }";

it("keeps runtime reflection changes behind manual review", () => {
  expect(Object.getOwnPropertyNames(ErasedPrivate.prototype)).toContain("load");
  expect(Object.getOwnPropertyNames(RuntimePrivate.prototype)).not.toContain("load");
  expect(rule.meta?.fixable).toBe("code");
});

const TESTER = ruleTester({ cwd: FIXTURES });

TESTER.run("prefer-ecmascript-private-members", rule, typed({
  valid: [
    RUNTIME_PRIVATE_EXAMPLE,
    "class Service { public run() {} protected extend() {} }",
    "class Service { private constructor() {} static create() { return new Service(); } }",
    "abstract class Service { abstract privateMethod(): void }",
    "class Service { private ['run']() {} }",
    "class Service { @logged private run() {} }",
    "class Service { private override run() {} }",
    { code: "declare class Service { private run(): void }", filename: "service.d.ts" },
    { code: "class Service { private run() {} }", filename: "generated/service.ts" },
  ],
  invalid: [
    { name: "fixes a closed unused module class", code: "export {}; class Vault { private read() { return 1; } open() { return this.read(); } }", output: "export {}; class Vault { #read() { return 1; } open() { return this.#read(); } }", errors: [{ messageId: "preferEcmascriptPrivate" }] },
    { name: "preserves class decorators with implicit observation", code: "export {}; @register class Vault { private read() { return 1; } }", output: null, errors: [{ messageId: "preferEcmascriptPrivate" }] },
    { name: "preserves a class that leaks through static execution", code: "export {}; class Vault { static leak = register(this); private read() { return 1; } }", output: null, errors: [{ messageId: "preferEcmascriptPrivate" }] },
    { name: "preserves a class called through its outer binding", code: "export {}; class Vault { private read() { return 1; } } consume(new Vault());", output: null, errors: [{ messageId: "preferEcmascriptPrivate" }] },
    { name: "does not rewrite a class escaping through static this", code: "declare function register(value: unknown): void; class Service { static { register(this); } private load() { return 1; } run() { return this.load(); } }", output: null, errors: [{ messageId: "preferEcmascriptPrivate" }] },
    {
      name: "reports the documented method without an automatic runtime change",
      code: TYPESCRIPT_PRIVATE_EXAMPLE,
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "read" } }],
    },
    {
      name: "preserves an async method for manual migration",
      code: "class Service { private async load() { return 1; } run() { return this.load(); } }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "reports a getter setter pair once without rewriting it",
      code: "class Box { private get value() { return 1; } private set value(next: number) {} read() { return this.value; } }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "value" } }],
    },
    {
      name: "reports a static method without an unsafe fix",
      code: "class Service { private static load() {} }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "reports computed reflective access without a fix",
      code: "class Service { private load() {} run() { return this['load'](); } }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "reports external access without a fix",
      code: "class Service { private load() {} } const service = new Service(); service.load();",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "reports a private field",
      code: "class Box { private value = 1; read() { return this.value; } }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "value" } }],
    },
    {
      name: "does not autofix an exported class whose bracket callers can live in another module",
      code: "export class Service { private load() {} }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "does not autofix a class referenced outside its body",
      code: "class Service { private load() {} } export const service = new Service();",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "does not partially convert overload declarations",
      code: "class Service { private load(value: string): string; private load(value: number): number; private load(value: string | number) { return value; } run() { return this.load(1); } }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "preserves a comment between the private modifier and member name",
      code: "class Service { private /* reflection contract */ load() {} }",
      output: null,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
  ],
}));

TESTER.run("prefer-ecmascript-private-members without types", rule, {
  valid: [{ code: TYPESCRIPT_PRIVATE_EXAMPLE, settings: { sarj: { typeAware: false } } }],
  invalid: [],
});
