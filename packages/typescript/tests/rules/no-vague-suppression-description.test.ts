import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-vague-suppression-description.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
  linterOptions: { reportUnusedDisableDirectives: false },
});

ruleTester.run("no-vague-suppression-description", rule, {
  valid: [
    "// eslint-disable-next-line no-console -- CLI output is the public interface\nconsole.log(value);",
    "// @ts-expect-error -- vendor declaration omits the runtime overload added in v4\nlegacy.call(value);",
    "// @ts-expect-error: generated SDK types model this nullable response as required\nread(value);",
    "// false positive in prose, not a directive\nconst value = 1;",
    {
      filename: "/repo/src/generated/client.ts",
      code: "// @ts-expect-error -- needed\ncall();",
    },
  ],
  invalid: [
    {
      code: "// eslint-disable-next-line no-console -- needed\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// eslint-disable-next-line no-console -- false positive\nconsole.log(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "// @ts-expect-error: to satisfy linter\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
    {
      code: "/* @ts-ignore -- intentional */\nlegacy.call(value);",
      errors: [{ messageId: "vagueDescription" }],
    },
  ],
});
