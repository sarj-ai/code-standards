import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION } from "../../src/rules/no-unsafe-test-double-cast.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-unsafe-test-double-cast", rule, {
  valid: [
    { name: "accepts the public typed-fake example", filename: "service.test.ts", code: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.examples[0].files[0].source },
    { name: "ignores ordinary payload casts", filename: "schema.test.ts", code: "const payload = {} as unknown as Payload;" },
    { name: "ignores ordinary immutable fixture aliases", filename: "schema.test.ts", code: "const raw = { id: '1' }; const payload = raw as unknown as Payload;" },
    { name: "ignores a directly typed mock", filename: "service.test.ts", code: "import { vi } from 'vitest'; const read = vi.fn<Client['read']>();" },
    { name: "ignores locally shadowed Vitest namespaces", filename: "service.test.ts", code: "const vi = { fn: () => () => undefined }; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores unrelated imports named vi", filename: "service.test.ts", code: "import { vi } from './helpers'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores mutable mock aliases", filename: "service.test.ts", code: "import { vi } from 'vitest'; let read = vi.fn(); read = realRead; const client = { read } as unknown as Client;" },
    { name: "ignores helper return values", filename: "service.test.ts", code: "import { vi } from 'vitest'; function makeClient() { return { read: vi.fn() }; } const client = makeClient() as unknown as Client;" },
    { name: "ignores production files", filename: "service.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores generated files", filename: "tests/generated/service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
  ],
  invalid: [
    { name: "reports the public example", filename: "service.test.ts", code: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports nested mock members", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { nested: { read: vi.fn() } } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports Jest mock factories", filename: "service.spec.ts", code: "const client = { read: jest.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports angle-bracket double assertions", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client><unknown>{ read: vi.fn() };", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports fluent mock factory chains", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn().mockResolvedValue('ok') } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports immutable shorthand mock aliases", filename: "service.test.ts", code: "import { vi } from 'vitest'; const read = vi.fn().mockResolvedValue('ok'); const client = { read } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports immutable object aliases", filename: "service.test.ts", code: "import { vi } from 'vitest'; const read = vi.fn(); const partial = { read }; const client = partial as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports transitive immutable aliases", filename: "service.test.ts", code: "import { vi } from 'vitest'; const mockRead = vi.fn(); const read = mockRead; const partial = { read }; const client = partial as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports renamed Vitest imports", filename: "service.test.ts", code: "import { vi as test } from 'vitest'; const client = { read: test.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports renamed Jest imports", filename: "service.test.ts", code: "import { jest as test } from '@jest/globals'; const client = { read: test.spyOn(source, 'read') } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports mixed assertion syntax", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client>({ read: vi.fn() } as unknown);", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports reverse mixed assertion syntax", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = (<unknown>{ read: vi.fn() }) as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports any bridge assertions", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as any as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
  ],
});
