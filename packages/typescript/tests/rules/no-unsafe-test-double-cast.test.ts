// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION } from "../../src/rules/no-unsafe-test-double-cast.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-unsafe-test-double-cast", rule, {
  valid: [
    { name: "ignores a parameter named vi", filename: "service.test.ts", code: "function build(vi: LocalBuilder) { return { read: vi.fn() } as unknown as Client; }" },
    { name: "ignores a local jest object", filename: "service.test.ts", code: "const jest = localBuilder; const client = { read: jest.fn() } as unknown as Client;" },
    { name: "ignores an unrelated vi import", filename: "service.test.ts", code: "import { vi } from './builder'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores a shadowed Vitest import", filename: "service.test.ts", code: "import { vi } from 'vitest'; function build(vi: LocalBuilder) { return { read: vi.fn() } as unknown as Client; }" },
    { name: "ignores type-only namespaces", filename: "service.test.ts", code: "import type { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores unsupported framework exports", filename: "service.test.ts", code: "import { jest } from 'vitest'; const client = { read: jest.fn() } as unknown as Client;" },
    { name: "accepts the public typed-fake example", filename: "service.test.ts", code: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.examples[0].files[0].source },
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
    { name: "reports the public example", filename: "service.test.ts", code: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.examples[1].files[0].source, output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports nested mock members", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { nested: { read: vi.fn() } } as unknown as Client;", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports Jest mock factories", filename: "service.spec.ts", code: "const client = { read: jest.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports angle-bracket double assertions", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client><unknown>{ read: vi.fn() };", output: null, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "mock-backed-double-cast-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "service.test.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "service.test.ts",
        "source": "import { vi } from 'vitest'; const client = { read: vi[\"fn\"]() } as unknown as Client;"
      }
    ]
  },
  {
    "id": "mock-backed-double-cast-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "service.test.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "service.test.ts",
        "source": "import { vi } from 'vitest'; const client = { read: vi[auditDynamicMember]() } as unknown as Client;"
      }
    ]
  }
] } });
});
