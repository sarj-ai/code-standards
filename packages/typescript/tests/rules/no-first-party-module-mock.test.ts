import rule from "../../src/rules/no-first-party-module-mock.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-first-party-module-mock", rule, {
  valid: [
    { name: "keeps interpolated module specifiers opaque", filename: "action.test.ts", code: 'import { vi } from "vitest"; vi.mock(`./${moduleName}`);' },
    { name: "keeps a third-party module through a const assertion", filename: "action.test.ts", code: 'import { vi } from "vitest"; vi.mock(("react" as const));' },
    { name: "keeps unresolved computed mocking methods opaque", filename: "action.test.ts", code: 'import { vi } from "vitest"; vi[method](`./service`);' },

    { name: "allows a literal virtual Jest module", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./virtual', () => ({}), { virtual: true });" },
    { name: "allows virtual doMock through an import alias", filename: "action.test.ts", code: "import { jest as mocks } from '@jest/globals'; mocks.doMock('./virtual', () => ({}), { 'virtual': true });" },
    { name: "excludes unknown Jest options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), options);" },
    { name: "excludes spread Jest options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), { ...options });" },
    { name: "excludes unknown virtual flag", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), { virtual: enabled });" },
    { name: "ignores type-only Vitest imports", filename: "action.test.ts", code: "import type { vi } from 'vitest'; vi.mock('./service');" },
    { name: "ignores unsupported framework exports", filename: "action.test.ts", code: "import { jest } from 'vitest'; jest.mock('./service');" },
    { name: "ignores nested import shadowing", filename: "action.test.ts", code: "import { vi } from 'vitest'; function run(vi: LocalBuilder) { vi.mock('./service'); }" },
    { name: "accepts the public injection example", filename: "action.test.ts", code: "const result = await runAction({ service: recordingService });" },
    { name: "allows third-party modules", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock('next/cache');" },
    { name: "allows dynamic module names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(moduleName);" },
    { name: "ignores shadowed vi", filename: "action.test.ts", code: "const vi = localMocks; vi.mock('./service');" },
    { name: "ignores production files", filename: "action.ts", code: "import { vi } from 'vitest'; vi.mock('./service');" },
    { name: "ignores generated files", filename: "tests/generated/action.test.ts", code: "import { vi } from 'vitest'; vi.mock('./service');" },
  ],
  invalid: [
    { name: "retains a relative no-substitution template module", filename: "action.test.ts", code: 'import { vi } from "vitest"; vi.mock(`./service`);', errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "retains a relative module through a const assertion", filename: "action.test.ts", code: 'import { vi } from "vitest"; vi.mock(("./service" as const));', errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "recognizes imported static computed mocking methods", filename: "action.test.ts", code: 'import { vi } from "vitest"; vi["mock"](`./service`);', errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },

    { name: "reports an explicitly nonvirtual Jest module", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), { virtual: false });", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports empty Jest options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service', () => ({}), {});", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "resolves the vitest export", filename: "action.test.ts", code: "import { vitest as mocks } from 'vitest'; mocks.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports the public relative-module example", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock('./service', () => ({ run: vi.fn() }));", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports parent modules", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.doMock('../services');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "../services" } }] },
    { name: "supports configured aliases", filename: "action.test.ts", options: [{ additionalModulePrefixes: ["@/"] }], code: "import { vi } from 'vitest'; vi.mock('@/services');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "@/services" } }] },
    { name: "supports aliased Vitest imports", filename: "action.test.ts", code: "import { vi as mocks } from 'vitest'; mocks.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "supports Jest globals imports", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
  ],
});

RULE_TESTER.run("preserves outcomes for static member access and unknown member keys", rule, {
  valid: [
    {"name": "relative-module-mock-dynamic-member", "filename": "action.test.ts", "code": "import { vi } from 'vitest'; vi[auditDynamicMember]('./service', () => ({ run: vi[auditDynamicMember]() }));"},
  ],
  invalid: [
    {"name": "relative-module-mock-static-member", "filename": "action.test.ts", "code": "import { vi } from 'vitest'; vi[\"mock\"]('./service', () => ({ run: vi[\"fn\"]() }));", "errors": [{"messageId": "noFirstPartyModuleMock"}] },
  ],
});

RULE_TESTER.run("no-first-party-module-mock retained extensions", rule, {
  valid: [
    { name: "preserves virtual ESM modules", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.unstable_mockModule('./virtual.js', () => ({}), { virtual: true });" },
    { name: "preserves opaque ESM options", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.unstable_mockModule('./service.js', () => ({}), options);" },
    { name: "preserves third-party ESM mocks", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.unstable_mockModule('external-package', () => ({}));" },
    { name: "preserves shadowed ESM APIs", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; function check(jest: LocalMocks) { jest.unstable_mockModule('./service.js', () => ({})); }" },
    { name: "does not invent a Vitest ESM API", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.unstable_mockModule('./service.js', () => ({}));" },
    { name: "preserves type-only ESM imports", filename: "action.test.ts", code: "import type { jest } from '@jest/globals'; jest.unstable_mockModule('./service.js', () => ({}));" },
  ],
  invalid: [
    { name: "recognizes the Jest ESM API", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.unstable_mockModule('./service.js', () => ({}));", output: null, errors: [{ messageId: "noFirstPartyModuleMock" }] },
    { name: "recognizes an aliased ESM import", filename: "action.test.ts", code: "import { jest as mocks } from '@jest/globals'; mocks.unstable_mockModule('../service.js', async () => ({}));", output: null, errors: [{ messageId: "noFirstPartyModuleMock" }] },
    { name: "recognizes literal computed ESM methods", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest['unstable_mockModule']('./service.js', () => ({}), { virtual: false });", output: null, errors: [{ messageId: "noFirstPartyModuleMock" }] },
  ],
});
