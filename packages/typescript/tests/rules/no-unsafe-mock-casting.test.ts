import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-unsafe-mock-casting.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-unsafe-mock-casting", rule, {
  valid: [
    { code: "const m = vi.mocked(myFn);" },
    { code: "const m = jest.mocked(myFn);" },
    { code: "const m = myFn as MyCustomMock;" },
    { code: "const m = <MyCustomMock>myFn;" },
    { code: "const m = myFn as string;" },
    // A generated file could hypothetically do it, but we ignore generated files
    { 
      code: "const m = myFn as jest.Mock;",
      filename: "test.generated.ts",
    }
  ],
  invalid: [
    {
      code: "const m = myFn as Mock;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
    {
      code: "const m = myFn as vi.Mock;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
    {
      code: "const m = myFn as jest.Mock;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
    {
      code: "const m = myFn as MockInstance;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
    {
      code: "const m = myFn as SpyInstance;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
    {
      code: "const m = <Mock>myFn;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
    {
      code: "const m = <jest.Mock>myFn;",
      errors: [{ messageId: "unsafeMockCast" }],
    },
  ],
});
