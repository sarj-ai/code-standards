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
    { name: "ignores a directly typed mock", filename: "service.test.ts", code: "import { vi } from 'vitest'; const read = vi.fn<Client['read']>();" },
    { name: "ignores production files", filename: "service.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
    { name: "ignores generated files", filename: "tests/generated/service.test.ts", code: "import { vi } from 'vitest'; const client = { read: vi.fn() } as unknown as Client;" },
  ],
  invalid: [
    { name: "reports the public example", filename: "service.test.ts", code: NO_UNSAFE_TEST_DOUBLE_CAST_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports nested mock members", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = { nested: { read: vi.fn() } } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports Jest mock factories", filename: "service.spec.ts", code: "const client = { read: jest.fn() } as unknown as Client;", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
    { name: "reports angle-bracket double assertions", filename: "service.test.ts", code: "import { vi } from 'vitest'; const client = <Client><unknown>{ read: vi.fn() };", errors: [{ messageId: "noUnsafeTestDoubleCast" }] },
  ],
});
