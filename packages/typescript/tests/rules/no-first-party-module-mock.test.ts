import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION } from "../../src/rules/no-first-party-module-mock.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser } });

RULE_TESTER.run("no-first-party-module-mock", rule, {
  valid: [
    { name: "accepts the public injection example", filename: "action.test.ts", code: NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION.examples[0].files[0].source },
    { name: "allows third-party modules", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock('next/cache');" },
    { name: "allows dynamic module names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(moduleName);" },
    { name: "allows dynamic template module names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(`./${moduleName}`);" },
    { name: "allows dynamic imported module names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(import(moduleName));" },
    { name: "ignores shadowed vi", filename: "action.test.ts", code: "const vi = localMocks; vi.mock('./service');" },
    { name: "ignores an inner shadow of imported vi", filename: "action.test.ts", code: "import { vi } from 'vitest'; function replace(vi: LocalMocks) { vi.mock('./service'); }" },
    { name: "does not treat Vitest as Jest", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.setMock('./service', fakeService);" },
    { name: "ignores unrelated namespace imports", filename: "action.test.ts", code: "import * as helpers from './helpers'; helpers.vi.mock('./service');" },
    { name: "ignores production files", filename: "action.ts", code: "import { vi } from 'vitest'; vi.mock('./service');" },
    { name: "ignores generated files", filename: "tests/generated/action.test.ts", code: "import { vi } from 'vitest'; vi.mock('./service');" },
  ],
  invalid: [
    { name: "reports the public relative-module example", filename: "action.test.ts", code: NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION.examples[1].files[0].source, errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports parent modules", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.doMock('../services');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "../services" } }] },
    { name: "supports configured aliases", filename: "action.test.ts", options: [{ additionalModulePrefixes: ["@/"] }], code: "import { vi } from 'vitest'; vi.mock('@/services');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "@/services" } }] },
    { name: "supports aliased Vitest imports", filename: "action.test.ts", code: "import { vi as mocks } from 'vitest'; mocks.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "supports Jest globals imports", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports static template module names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(`./service`);", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports Vitest static import expressions", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi.mock(import('./service'));", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports computed static method names", filename: "action.test.ts", code: "import { vi } from 'vitest'; vi['mock']('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports Jest setMock", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.setMock('./service', fakeService);", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "reports Jest unstable module mocks", filename: "action.test.ts", code: "import { jest } from '@jest/globals'; jest.unstable_mockModule('../service', factory);", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "../service" } }] },
    { name: "supports Vitest namespace imports", filename: "action.test.ts", code: "import * as vitest from 'vitest'; vitest.vi.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
    { name: "supports Jest namespace imports", filename: "action.test.ts", code: "import * as globals from '@jest/globals'; globals.jest.mock('./service');", errors: [{ messageId: "noFirstPartyModuleMock", data: { module: "./service" } }] },
  ],
});
