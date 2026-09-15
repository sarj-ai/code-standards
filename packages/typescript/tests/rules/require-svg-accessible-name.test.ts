import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-svg-accessible-name.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
  defaultFilenames: { ts: "/repo/src/action.ts", tsx: "/repo/src/action.tsx" },
});

RULE_TESTER.run("require-svg-accessible-name", rule, {
  valid: [
    "<Graphic render={<svg />} />",
    '<div aria-hidden="true"><svg /></div>',
    '<svg aria-label="Sales trend" />',
    '<svg aria-labelledby="chart-title" />',
    '<svg><title>Sales trend</title><path d="M0 0" /></svg>',
    "<svg><title>{title}</title></svg>",
    '<svg aria-hidden="true" />',
    "<svg aria-hidden={true} />",
    '<svg role="presentation" />',
    '<svg role="none" />',
    "<svg {...props}><path /></svg>",
    "<svg aria-label={label} />",
    "<Svg />",
    { code: "<svg />", filename: "/repo/src/generated/icon.tsx" },
    { code: "<svg />", filename: "/repo/src/icon.stories.tsx" },
  ],
  invalid: [
    { code: "<svg />", errors: [{ messageId: "missingName" }] },
    { code: "<svg><path /></svg>", errors: [{ messageId: "missingName" }] },
    {
      code: "<svg><title> </title></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: "<svg aria-hidden={false}><path /></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<svg aria-label=""><path /></svg>',
      errors: [{ messageId: "missingName" }],
    },
    {
      code: "<svg><desc>A longer description</desc></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: "<svg><g><title>Nested group name</title></g></svg>",
      errors: [{ messageId: "missingName" }],
    },
    {
      code: '<svg title="Not an SVG title element" />',
      errors: [{ messageId: "missingName" }],
    },
  ],
});
