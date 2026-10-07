import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION } from "../../src/rules/no-first-party-module-mock.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-first-party-module-mock", rule, {
  valid: [
    { name: "allows a literal virtual Jest module", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./virtual', () => ({}), { virtual: true });" },
    { name: "allows virtual doMock through an import alias", filename: "action.test.ts", code: "import { jest as mocks } from '@jest/globals'; mocks.doMock('./virtual', () => ({}), { 'virtual': true });" },
    { name: "excludes unknown Jest options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), options);" },
    { name: "excludes spread Jest options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), { ...options });" },
    { name: "excludes unknown virtual flag", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), { virtual: enabled });" },
    { name: "ignores type-only Vitest imports", filename: "action.test.ts", code: "import type { vi } from 'vitest'; vi.mock('./service');" },
    { name: "ignores unsupported framework exports", filename: "action.test.ts", code: "import { jest } from 'vitest'; jest.mock('./service');" },
    { name: "ignores nested import shadowing", filename: "action.test.ts", code: "import { vi } from 'vitest'; function run(vi: LocalBuilder) { vi.mock('./service'); }" },
    { name: "accepts the public injection example", filename: "action.test.ts", code: NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION.examples[0].files[0].source },
    { name: "allows third-party modules", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock('next/cache');" },
    { name: "allows dynamic module names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(moduleName);" },
    { name: "ignores shadowed vi", filename: "action.test.ts", code: "const vi = localMocks; vi.mock('./service');" },
    { name: "ignores production files", filename: "action.ts", code: "import { vi } from 'vitest'; vi.mock('./service');" },
    { name: "ignores generated files", filename: "tests/generated/action.test.ts", code: "import { vi } from 'vitest'; vi.mock('./service');" },
  ],
  invalid: [
    { name: "reports an explicitly nonvirtual Jest module", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), { virtual: false });", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports empty Jest options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), {});", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "resolves the vitest export", filename: "action.test.ts", code: "import { vitest as mocks } from 'vitest'; mocks.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports the public relative-module example", filename: "action.test.ts", code: NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports parent modules", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.doMock('../services');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "../services" } }] },
    { name: "supports configured aliases", filename: "action.test.ts", options: [{ additionalModulePrefixes: ["@/"] }], code: "import { vi } from 'vitest'; vi.mock('@/services');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "@/services" } }] },
    { name: "supports aliased Vitest imports", filename: "action.test.ts", code: "import { vi as mocks } from 'vitest'; mocks.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "supports Jest globals imports", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "relative-module-mock-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "action.test.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "action.test.ts",
        "source": "import { vi } from 'vitest'; vi[\"mock\"]('./service', () => ({ run: vi[\"fn\"]() }));"
      }
    ]
  },
  {
    "id": "relative-module-mock-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "action.test.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "action.test.ts",
        "source": "import { vi } from 'vitest'; vi[auditDynamicMember]('./service', () => ({ run: vi[auditDynamicMember]() }));"
      }
    ]
  }
] } });
});
