import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-single-sentence-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("prefer-single-sentence-comment", rule, {
  valid: [
    "// One useful constraint.\nconst value = 1;",
    "// First. Second. Third.\nconst value = 1;",
    { code: "// Generated. With two sentences.\nconst value = 1;", filename: "client.generated.ts" },
    "/** @example One. Two. */\nexport function value(): number { return 1; }",
  ],
  invalid: [
    {
      code: "// First fact. Second fact.\nconst value = 1;",
      errors: [{ messageId: "preferOneSentence" }],
    },
    {
      code: "// First fact.\n// Second fact.\nconst value = 1;",
      errors: [{ messageId: "preferOneSentence" }],
    },
  ],
});
