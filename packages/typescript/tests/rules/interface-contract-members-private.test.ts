import rule from "../../src/rules/interface-contract-members-private.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

const RUNTIME_PRIVATE_EXAMPLE = "interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }";
const EXTRA_METHOD_EXAMPLE = "interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } read() {} }";

const RULE_TESTER = ruleTester({ cwd: FIXTURES });

RULE_TESTER.run("interface-contract-members-private", rule, typed({
  valid: [
    RUNTIME_PRIVATE_EXAMPLE,
    "class Standalone { helper() {} }",
    "interface Base { load(): void } interface Store extends Base {} class DiskStore implements Store { load() {} }",
    "interface Store { readonly value: number } class DiskStore implements Store { get value() { return 1; } }",
    "interface Store { load(): void } abstract class BaseStore implements Store { abstract load(): void; helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} private helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} #helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { static create() {} load() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} protected flush() {} }",
    "class Base { helper() {} } interface Store { load(): void } class DiskStore extends Base implements Store { load() {} override helper() {} }",
    "interface Store { load(): void } class DiskStore implements Store { load() {} ['helper']() {} }",
    "class DiskStore implements MissingPackageContract { load() {} helper() {} }",
    { code: "interface Store { load(): void } class DiskStore implements Store { load() {} helper() {} }", filename: "generated/store.ts" },
  ],
  invalid: [
    { name: "removes explicit public accessibility when privatizing an inert helper", code: "export {}; interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } public read() {} }", output: "export {}; interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }", errors: [{ messageId: "nonContractMemberMustBePrivate" }] },
    { name: "fixes an unused module class without changing the interface", code: "export {}; interface Store { load(): void } class DiskStore implements Store { load() { this.read(); } read() {} }", output: "export {}; interface Store { load(): void } class DiskStore implements Store { load() { this.#read(); } #read() {} }", errors: [{ messageId: "nonContractMemberMustBePrivate" }] },
    { name: "preserves implicit static instance registration", code: "export {}; interface Store { load(): void } class DiskStore implements Store { static { register(new this()); } load() {} read() {} }", output: null, errors: [{ messageId: "nonContractMemberMustBePrivate" }] },
    {
      name: "reports the documented extra method without choosing its public API",
      code: EXTRA_METHOD_EXAMPLE,
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
      name: "reports a decorated method when no framework contract proves it public",
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
}));

RULE_TESTER.run("interface-contract-members-private without types", rule, {
  valid: [{ name: "reports nothing without type information, like the original's empty visitors", code: EXTRA_METHOD_EXAMPLE, settings: { sarj: { typeAware: false } } }],
  invalid: [],
});
