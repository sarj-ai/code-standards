import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-unlocalized-jsx-attributes.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
  defaultFilenames: { ts: "/repo/src/action.ts", tsx: "/repo/src/action.tsx" },
});

RULE_TESTER.run("no-unlocalized-jsx-attributes", rule, {
  valid: [
    '<input placeholder={t("search")} />',
    '<img alt="" />',
    '<div aria-labelledby="dialog-title" />',
    '<div data-testid="hello" />',
    '<input placeholder="Search" {...props} />',
    '<div translate="no"><input placeholder="Brand" /></div>',
    { code: '<input placeholder="Search" />', options: [{ enabled: false }] },
    {
      code: '<div aria-labelledby="dialog-title" />',
      options: [{ attributes: ["aria-labelledby"] }],
    },
  ],
  invalid: [
    {
      code: '<code title="Example code">token</code>',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<input placeholder="Search" />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<button aria-label={"Close"} />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<img alt="A mountain" />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<input {...props} translate="yes" placeholder="Search" />',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: '<Control caption="Welcome" />',
      options: [{ attributes: ["caption"] }],
      errors: [{ messageId: "unlocalized" }],
    },
  ],
});
