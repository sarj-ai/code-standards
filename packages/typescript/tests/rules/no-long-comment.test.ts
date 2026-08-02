import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-long-comment.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

new RuleTester().run("no-long-comment", rule, {
  valid: [
    "// First fact. Second fact.\nconst value = 1;",
    "// Supports e.g. version 2.1 at https://example.com/a. One constraint.\nconst value = 1;",
    { code: "// One. Two. Three.\nconst value = 1;", filename: "widget.stories.tsx" },
  ],
  invalid: [
    {
      code: "// First fact. Second fact. Third fact.\nconst value = 1;",
      errors: [{ messageId: "tooLong" }],
    },
    {
      code: "/** First fact. Second fact. Third fact. */\nexport const value = 1;",
      errors: [{ messageId: "tooLong" }],
    },
  ],
});
