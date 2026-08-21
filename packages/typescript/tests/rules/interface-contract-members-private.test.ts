import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  interfaceContractMembersPrivateDocumentation,
} from "../../src/rules/interface-contract-members-private.js";

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

ruleTester.run("interface-contract-members-private", rule, {
  valid: [
    interfaceContractMembersPrivateDocumentation.examples[0].files[0].source,
    "class Standalone { helper() {} }",
    "interface Base { load(): void } interface Store extends Base {} class DiskStore implements Store { load() {} }",
    "interface Store { readonly value: number } class DiskStore implements Store { get value() { return 1; } }",
    "interface Store { load(): void } abstract class BaseStore implements Store { abstract load(): void; helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} private helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} #helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { static create() {} load() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} ['helper']() {} }",
    "class DiskStore implements MissingPackageContract { load() {} helper() {} }",
    { code: "interface Store { load(): void } class DiskStore implements Store { load() {} helper() {} }", filename: "generated/store.ts" },
  ],
  invalid: [
    {
      name: "reports the documented extra method without choosing its public API",
      code: interfaceContractMembersPrivateDocumentation.examples[1].files[0].source,
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "read" } }],
    },
    {
      name: "resolves a transitive contract without an unsafe public API fix",
      code: "interface Base { load(): void } interface Store extends Base {} class DiskStore implements Store { load() { this.flush(); } flush() {} }",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "flush" } }],
    },
    {
      name: "reports protected extension behavior without a fix",
      code: "interface Store { load(): void } class DiskStore implements Store { load() {} protected flush() {} }",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "flush" } }],
    },
    {
      name: "reports an override without a fix",
      code: "class Base { helper() {} } interface Store { load(): void } class DiskStore extends Base implements Store { load() {} override helper() {} }",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "helper" } }],
    },
    {
      name: "reports a decorated helper without a fix",
      code: "interface Store { load(): void } class DiskStore implements Store { load() {} @logged helper() {} }",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "helper" } }],
    },
    {
      name: "reports externally called extra API without a fix",
      code: "interface Store { load(): void } class DiskStore implements Store { load() {} helper() {} } new DiskStore().helper();",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "helper" } }],
    },
    {
      name: "does not autofix an exported interface-backed class whose callers can live in another module",
      code: "interface Store { load(): void } export class DiskStore implements Store { load() {} helper() {} }",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "helper" } }],
    },
    {
      name: "does not partially privatize an overloaded method",
      code: "interface Store { load(): void } class DiskStore implements Store { load() {} helper(value: string): string; helper(value: number): number; helper(value: string | number) { return value; } }",
      output: null,
      errors: [{ messageId: "nonContractMemberMustBePrivate", data: { name: "helper" } }],
    },
  ],
});
