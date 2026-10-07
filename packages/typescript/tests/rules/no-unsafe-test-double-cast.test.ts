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
    { name: "resolves an aliased Vitest namespace", filename: "service.test.ts", code: "import { vi as mocks } from 'vitest'; const client = { read: mocks.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "resolves an aliased Jest namespace", filename: "service.test.ts", code: "import { jest as mocks } from '@jest/globals'; const client = { read: mocks.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "resolves the vitest export", filename: "service.test.ts", code: "import { vitest as mocks } from 'vitest'; const client = { read: mocks.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports mixed assertion syntax", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client>({ read: vi.fn() } as unknown);", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports reverse mixed assertion syntax", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = (<unknown>{ read: vi.fn() }) as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports the public example", filename: "service.test.ts", code: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports nested mock members", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { nested: { read: vi.fn() } } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports Jest mock factories", filename: "service.spec.ts", code: "const client = { read: jest.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports angle-bracket double assertions", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client><unknown>{ read: vi.fn() };", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
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
