/** @fileoverview no-first-party-module-mock — the documentation and executable examples of `@sarj/no-first-party-module-mock`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_FIRST_PARTY_MODULE_MOCK_DOCUMENTATION = {
  summary: "Prefer injected collaborators over mocking maintained first-party modules in tests.",
  rationale: "Replacing an owned module couples tests to its lookup path and can verify mock wiring while bypassing the real implementation contract.",
  remediation: "Extract a narrow port or pure core operation and inject a typed fake; retain module mocking only when module lookup or bootstrap behavior is the contract.",
  category: "testing",
  requiresTypeInformation: false,
  runtimeImports: ["@jest/globals", "vitest"],
  references: ["https://github.com/dmmulroy/anti-slop/blob/13909c9e07590f5a85d93c62712259fe14a883f7/src/rules/no-module-mocking.ts"],
  limitations: ["Only generated-free test files, provenance-resolved Vitest mock/doMock or Jest mock/doMock/unstable_mockModule APIs, relative module specifiers, and explicitly configured first-party prefixes are checked. Third-party, framework, Jest virtual modules, unknown Jest options, type-only imports and dynamic module names are excluded. Unimported framework globals and indirect namespace aliases are not inferred."],
  examples: [
    { id: "injected-service", title: "Inject a narrow service port", outcome: "no-match", files: [{ path: "action.test.ts", source: "const result = await runAction({ service: recordingService });" }], focusPath: "action.test.ts", expectedCount: 0, public: true },
    { id: "relative-module-mock", title: "Do not replace an owned module", outcome: "match", files: [{ path: "action.test.ts", source: "import { vi } from 'vitest'; vi.mock('./service', () => ({ run: vi.fn() }));" }], focusPath: "action.test.ts", expectedCount: 1, public: true },
    {"id": "jest-esm-before", "scenarioId": "jest-esm", "title": "Exercise the maintained ESM implementation — before", "outcome": "match", "files": [{"path": "tests/service.test.ts", "source": "import { jest } from '@jest/globals'; jest.unstable_mockModule('./service.js', () => ({}));"}], "focusPath": "tests/service.test.ts", "expectedCount": 1, "public": true},
    {"id": "jest-esm-after", "scenarioId": "jest-esm", "title": "Exercise the maintained ESM implementation — after", "outcome": "no-match", "files": [{"path": "tests/service.test.ts", "source": "import { run } from './service.js'; run();"}], "focusPath": "tests/service.test.ts", "expectedCount": 0, "public": true},
  ],
} as const satisfies RuleDocumentation;
