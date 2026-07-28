import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/theme-no-raw-colors.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
});

ruleTester.run("theme-no-raw-colors", rule, {
  valid: [
    { code: "const color = 'primary';" },
    { code: "const bg = 'bg-primary';" },
    { code: "<div className=\"bg-primary\" />;" },
    { code: "<div style={{ color: 'var(--color-primary)' }} />;" },
    { code: "`bg-primary`" },
    { code: "const href = '/page#123456';" }, // Testing that it doesn't match a hash in a URL if it's attached to text
    { code: "const mixed = '#12345Z';" }, // Not a valid hex color
  ],
  invalid: [
    {
      code: "const color = '#FF0000';",
      errors: [{ messageId: "noRawHexColor" }],
    },
    {
      code: "const color = '#f00';",
      errors: [{ messageId: "noRawHexColor" }],
    },
    {
      code: "<div className=\"bg-[#FF0000]\" />;",
      errors: [{ messageId: "noRawHexColor" }],
    },
    {
      code: "<div style={{ color: '#00ff00' }} />;",
      errors: [{ messageId: "noRawHexColor" }],
    },
    {
      code: "const template = `bg-[#123456]`;",
      errors: [{ messageId: "noRawHexColor" }],
    },
    {
      code: "<div color=\"#11223344\" />;",
      errors: [{ messageId: "noRawHexColor" }],
    },
    {
      code: "<div>#ff0000</div>;",
      errors: [{ messageId: "noRawHexColor" }],
    },
  ],
});
