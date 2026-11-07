// vitest: shared-module-graph
import rule from "../../src/rules/no-unsafe-test-double-cast.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-unsafe-test-double-cast", rule, {
  valid: [
    { name: "ignores a parameter named vi", filename: "service.test.ts", code: "function build(vi: LocalBuilder) { return { read: vi.fn() } as unknown as Client; }" },
    { name: "ignores a local jest object", filename: "service.test.ts", code: "const jest = localBuilder; const client = { read: jest.fn() } as unknown as Client;" },
    { name: "ignores an unrelated vi import", filename: "service.test.ts", code: "import { vi } from './builder'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores a shadowed Vitest import", filename: "service.test.ts", code: "import { vi } from 'vitest'; function build(vi: LocalBuilder) { return { read: vi.fn() } as unknown as Client; }" },
    { name: "ignores type-only namespaces", filename: "service.test.ts", code: "import type { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores unsupported framework exports", filename: "service.test.ts", code: "import { jest } from 'vitest'; const client = { read: jest.fn() } as unknown as Client;" },
    { name: "accepts the public typed-fake example", filename: "service.test.ts", code: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" },
    { name: "ignores ordinary payload casts", filename: "schema.test.ts", code: "const payload = {} as unknown as Payload;" },
    { name: "ignores a directly typed mock", filename: "service.test.ts", code: "import { vi } from 'vitest'; const read = vi.fn<Client['read']>();" },
    { name: "ignores production files", filename: "service.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores generated files", filename: "tests/generated/service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
  ],
  invalid: [
    { name: "preserves a collaborator type whose only use would disappear", filename: "service.test.ts", code: "import { vi } from 'vitest'; interface Client { read(): string } const client = { read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "does not let simultaneous doubles witness the same type", filename: "service.test.ts", code: "import { vi } from 'vitest'; interface Client { read(): string } const first = { read: vi.fn() } as unknown as Client; const second = { read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }, { messageId: "noUnsafeTestDoubleCast" }] },
    { name: "checks a generic type erased despite an exported collaborator", filename: "service.test.ts", code: "import { vi } from 'vitest'; interface Client<T> { read(): T } export type KeptClient = Client<string>; type OnlyHere = string; const client = { read: vi.fn() } as unknown as Client<OnlyHere>;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "checks a type-only namespace erased by a double assertion", filename: "service.test.ts", code: "import { vi } from 'vitest'; import type * as contracts from './contracts.js'; const client = { read: vi.fn() } as unknown as contracts.Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "retains independently exported collaborator and generic types", filename: "service.test.ts", code: "import { vi } from 'vitest'; interface Client<T> { read(): T } type Payload = string; export type KeptClient = Client<Payload>; const client = { read: vi.fn() } as unknown as Client<Payload>;", output: "import { vi } from 'vitest'; interface Client<T> { read(): T } type Payload = string; export type KeptClient = Client<Payload>; const client = { read: vi.fn() };", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "retains a publicly typed namespace collaborator", filename: "service.test.ts", code: "import { vi } from 'vitest'; import type * as contracts from './contracts.js'; export type KeptClient = contracts.Client; const client = { read: vi.fn() } as unknown as contracts.Client;", output: "import { vi } from 'vitest'; import type * as contracts from './contracts.js'; export type KeptClient = contracts.Client; const client = { read: vi.fn() };", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves referenced collaborator contracts", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client; use(client);", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves exported collaborator contracts", filename: "service.test.ts", code: "import { vi } from 'vitest'; export const client = { read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves independent binding annotations", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client: Client = { read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves context-dependent implementations", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn((value) => value) } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves explicit mock generic contracts", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn<Client['read']>() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves arbitrary contextual methods", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn(), map(value) { return value; } } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves spreads", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { ...base, read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves accessors", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn(), get state() { return value; } } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves computed member contracts", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { [name]: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves array contextual contracts", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = [vi.fn()] as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves assertion comments", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } /* contract */ as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "preserves eval ownership", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client; eval('client');", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "resolves an aliased Vitest namespace", filename: "service.test.ts", code: "import { vi as mocks } from 'vitest'; const client = { read: mocks.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "resolves an aliased Jest namespace", filename: "service.test.ts", code: "import { jest as mocks } from '@jest/globals'; const client = { read: mocks.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "resolves the vitest export", filename: "service.test.ts", code: "import { vitest as mocks } from 'vitest'; const client = { read: mocks.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports mixed assertion syntax", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client>({ read: vi.fn() } as unknown);", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports reverse mixed assertion syntax", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = (<unknown>{ read: vi.fn() }) as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports the public example", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports nested mock members", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { nested: { read: vi.fn() } } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports Jest mock factories", filename: "service.spec.ts", code: "const client = { read: jest.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports angle-bracket double assertions", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client><unknown>{ read: vi.fn() };", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
  ],
});

RULE_TESTER.run("no-unsafe-test-double-cast documented examples", rule, {
  valid: [
    { name: "documented example typed-recording-fake", filename: "./service.test.ts", code: "const client = { read: async () => ({ id: '1' }) } satisfies Pick<Client, 'read'>;" },
    { name: "documented example mock-backed-double-cast-dynamic-member", filename: "./service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi[auditDynamicMember]() } as unknown as Client;" },
  ],
  invalid: [
    { name: "documented example mock-backed-double-cast", filename: "./service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "documented example safe-autofix", filename: "./service.test.ts", code: "import { vi } from 'vitest'; interface Client { read(): string } export type RetainedClient = Client; const client = { read: vi.fn() } as unknown as Client;", output: "import { vi } from 'vitest'; interface Client { read(): string } export type RetainedClient = Client; const client = { read: vi.fn() };", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "documented example mock-backed-double-cast-static-member", filename: "./service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi[\"fn\"]() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
  ],
});
