import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-logical-tailwind-utilities.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
  defaultFilenames: { ts: "/repo/src/action.ts", tsx: "/repo/src/action.tsx" },
});

RULE_TESTER.run("prefer-logical-tailwind-utilities", rule, {
  valid: [
    '<div className="ms-2 pe-4 text-start border-e rounded-ss-lg" />',
    '<div className="left-(--coordinate) right-0" />',
    '<div title="ml-2" />',
    "<div className={classes} />",
    '<div className="rtl:ml-2 ltr:mr-4" />',
    '<div className="bg-[url(https://example.com/ml-2)]" />',
    { code: '<div className="ml-2" />', options: [{ enabled: false }] },
    {
      code: '<div className="ml-2" />',
      options: [{ allowUtilities: ["ml-2"] }],
    },
    {
      code: '<div className="ml-2" />',
      filename: "/repo/src/generated/layout.tsx",
    },
    '<div className="ml-2" {...props} />',
    '<div className="ml-2" className="ms-2" />',
  ],
  invalid: [
    {
      code: '<div className="ml-2" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: { utility: "ml-2", replacement: "ms-2" },
        },
      ],
    },
    {
      code: '<div className="hover:!mr-2" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: { utility: "hover:!mr-2", replacement: "hover:!me-2" },
        },
      ],
    },
    {
      code: '<div className="md:-ml-2!" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: { utility: "md:-ml-2!", replacement: "md:-ms-2!" },
        },
      ],
    },
    {
      code: '<div className="[&:hover]:border-l-2" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: {
            utility: "[&:hover]:border-l-2",
            replacement: "[&:hover]:border-s-2",
          },
        },
      ],
    },
    {
      code: '<div className="rounded-tl-lg text-right" />',
      errors: [
        {
          messageId: "physicalUtility",
          data: {
            utility: "rounded-tl-lg text-right",
            replacement: "rounded-ss-lg text-end",
          },
        },
      ],
    },
    {
      code: '<div className="left-0" />',
      options: [{ checkInsets: true }],
      errors: [{ messageId: "physicalUtility" }],
    },
    {
      code: '<div {...props} className={"pl-2"} />',
      errors: [{ messageId: "physicalUtility" }],
    },
    {
      code: "<div className={`mr-2`} />",
      errors: [{ messageId: "physicalUtility" }],
    },
  ],
});
