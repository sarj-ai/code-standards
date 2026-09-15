import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-unlocalized-jsx-text.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
  defaultFilenames: { ts: "/repo/src/action.ts", tsx: "/repo/src/action.tsx" },
});

RULE_TESTER.run("no-unlocalized-jsx-text", rule, {
  valid: [
    '<p>{t("greeting")}</p>',
    "<div>123 — ✓</div>",
    '<div translate="no">Brand</div>',
    '<div translate="no"><span>Brand</span></div>',
    '<code>{"{{token}}"}</code>',
    "<code><span>request_id</span></code>",
    "<samp>ENOENT</samp>",
    { code: "<p>API</p>", options: [{ allowText: ["API"] }] },
    {
      code: 'import { Trans as Message } from "translations"; const view = <Message>Hello <strong>world</strong></Message>;',
      options: [
        {
          translationComponents: [{ module: "translations", export: "Trans" }],
        },
      ],
    },

    { code: "<div>Hello</div>", options: [{ enabled: false }] },
    { code: "<div>Hello</div>", filename: "/repo/src/view.test.tsx" },
    { code: "<div>Hello</div>", filename: "/repo/src/generated/view.tsx" },
  ],
  invalid: [
    {
      code: '<div className="title">Hello</div>',
      errors: [{ messageId: "unlocalized" }],
    },
    { code: '<div>{"Hello"}</div>', errors: [{ messageId: "unlocalized" }] },
    { code: "<div>مرحبا</div>", errors: [{ messageId: "unlocalized" }] },
    { code: "<div>保存</div>", errors: [{ messageId: "unlocalized" }] },
    {
      code: '<div translate="no"><span translate="yes">Hello</span></div>',
      errors: [{ messageId: "unlocalized" }],
    },
  ],
});
