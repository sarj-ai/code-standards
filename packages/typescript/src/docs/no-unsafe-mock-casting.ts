/** @fileoverview no-unsafe-mock-casting — the documentation and executable examples of `@sarj/no-unsafe-mock-casting`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNSAFE_MOCK_CASTING_DOCUMENTATION = {
  summary: "Disallow casting to mock types like `jest.Mock` or `vi.Mock`. Use `vi.mocked()` or `jest.mocked()` instead.",
  rationale: "A type assertion can claim an unmocked value is a mock and bypass checking between the original callable and the mock API.",
  remediation: "Create the mock or spy first, then use the framework's mocked helper to preserve the original value's type. The helper does not create or verify a runtime mock.",
  category: "testing",
  autofix: "safe",
  limitations: ["Only mock types imported from Vitest or Jest modules are inspected. mocked is a type helper, not runtime validation or a replacement for mock setup.",
    "Automatic fixes remove only an erased mock assertion from an unused private unannotated const initialized by an identifier, optionally through unknown assertions. Every erased named type/generic/namespace binding must retain an independent exported type use; potentially erased annotations and self references cannot witness each other. Evaluation is unchanged; referenced/exported bindings, contextual expressions, scripts, declaration files, eval and comments remain manual."],
  references: ["https://vitest.dev/api/vi.html#vi-mocked"],
  examples: [
    {
      id: "typed-mock-helper",
      title: "Use the framework helper",
      outcome: "no-match",
      files: [{ path: "src/client.test.ts", source: "import { vi } from 'vitest'; const client = { read: () => 'value' }; vi.spyOn(client, 'read'); const m = vi.mocked(client.read);" }],
      focusPath: "src/client.test.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "mock-type-assertion",
      title: "Do not assert that a value is a mock",
      outcome: "match",
      files: [{ path: "src/client.test.ts", source: "import type * as vi from \"vitest\"; const m = myFn as vi.Mock;" }],
      focusPath: "src/client.test.ts",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Retain an unused private value's actual inferred type",
      outcome: "match",
      files: [{ path: "src/autofix-example.ts", source: "import type { Mock } from 'vitest'; export type RetainedMock = Mock; declare const value: unknown; const fake = value as Mock;" }],
      fixedFiles: [{ path: "src/autofix-example.ts", source: "import type { Mock } from 'vitest'; export type RetainedMock = Mock; declare const value: unknown; const fake = value;" }],
      focusPath: "src/autofix-example.ts",
      expectedCount: 1,
    },
  ],
} as const satisfies RuleDocumentation;
