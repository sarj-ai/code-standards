import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-setup-file-mocks.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("prefer-setup-file-mocks", rule, {
  valid: [
    {
      code: `vi.mock("module", () => {});`,
      filename: "vitest.setup.ts",
    },
    {
      code: `jest.mock("module");`,
      filename: "jest.setup.js",
    },
    {
      code: `vi.spyOn(console, "log");`,
      filename: "foo.test.ts",
    },
    {
      code: `const mock = vi.fn();`,
      filename: "bar.spec.ts",
    },
    {
      code: `vi.mock("module");`,
      filename: "some-helper.ts",
    },
  ],
  invalid: [
    {
      code: `vi.mock("fs");`,
      filename: "my-module.test.ts",
      errors: [{ messageId: "preferSetupFileMocks" }],
    },
    {
      code: `jest.mock("fs", () => ({}));`,
      filename: "my-component.spec.tsx",
      errors: [{ messageId: "preferSetupFileMocks" }],
    },
    {
      code: `
        import { describe, it, vi } from 'vitest';
        vi.mock('axios');
        describe('suite', () => {});
      `,
      filename: "feature.test.ts",
      errors: [{ messageId: "preferSetupFileMocks" }],
    },
  ],
});
