import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION,
} from "../../src/rules/prefer-ecmascript-private-members.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

ruleTester.run("prefer-ecmascript-private-members", rule, {
  valid: [
    PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION.examples[0].files[0].source,
    "class Service { public run() {} protected extend() {} }",
    "abstract class Service { abstract privateMethod(): void }",
    "class Service { private ['run']() {} }",
    "class Service { @logged private run() {} }",
    "class Service { private override run() {} }",
    { code: "declare class Service { private run(): void }", filename: "service.d.ts" },
    { code: "class Service { private run() {} }", filename: "generated/service.ts" },
  ],
  invalid: [
    {
      name: "fixes the documented method and its exact reference",
      code: PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION.examples[1].files[0].source,
      output: PREFER_ECMASCRIPT_PRIVATE_MEMBERS_DOCUMENTATION.examples[1].fixedFiles?.[0]?.source,
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "read" } }],
    },
    {
      name: "fixes an async method without deleting async",
      code: "class Service { private async load() { return 1; } run() { return this.load(); } }",
      output: "class Service { async #load() { return 1; } run() { return this.#load(); } }",
      errors: [{ messageId: "preferEcmascriptPrivate", data: { name: "load" } }],
    },
    {
      name: "fixes a getter setter pair once",
      code: "class Box { private get value() { return 1; } private set value(next: number) {} read() { return this.value; } }",
      output: "class Box { get #value() { return 1; } set #value(next: number) {} read() { return this.#value; } }",
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
      output: "class Box { #value = 1; read() { return this.#value; } }",
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
});
