import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-shadcn.js";

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

ruleTester.run("prefer-shadcn", rule, {
  valid: [
    // FP guard, corpus: react-router/packages/react-router/__tests__/dom/data-browser-router-test.tsx:1415
    // — the smallest DOM that makes a router assertion reachable, not a UI.
    {
      code: 'const el = <input name="test" value="value" />;',
      filename: "/repo/packages/x/__tests__/dom/data-browser-router-test.tsx",
    },
    // shadcn primitives — the prescribed components.
    { code: "const x = <Input value='' onChange={() => {}} />;" },
    { code: "const x = <Select><option /></Select>;" },
    { code: "const x = <Textarea />;" },
    { code: "const x = <Dialog open />;" },
    // `<button>` and `<table>` were dropped from the forbid list (100% FP).
    { code: "const x = <button type='button'>click</button>;" },
    { code: "const x = <table><tbody /></table>;" },
    // Non-form elements are unrelated.
    { code: "const x = <div className='wrapper' />;" },
    // `type="hidden"` has no shadcn primitive — skipped.
    { code: "const x = <input type='hidden' value='x' />;" },
  ],
  invalid: [
    // Real screens still fire.
    {
      code: 'const el = <input name="q" />;',
      filename: "/repo/src/app/search/page.tsx",
      errors: [{ messageId: "preferShadcn" }],
    },
    {
      code: "const x = <input type='text' />;",
      errors: [
        {
          messageId: "preferShadcn",
          data: { element: "input", replacement: "Input", lowercase: "input" },
        },
      ],
    },
    // No type → generic Input.
    {
      code: "const x = <input value='' />;",
      errors: [
        {
          messageId: "preferShadcn",
          data: { element: "input", replacement: "Input", lowercase: "input" },
        },
      ],
    },
    // type-aware mapping to the correct primitive.
    {
      code: "const x = <input type='checkbox' />;",
      errors: [
        {
          messageId: "preferShadcn",
          data: { element: "input", replacement: "Checkbox", lowercase: "checkbox" },
        },
      ],
    },
    {
      code: "const x = <input type='radio' name='g' />;",
      errors: [
        {
          messageId: "preferShadcn",
          data: { element: "input", replacement: "RadioGroup", lowercase: "radio-group" },
        },
      ],
    },
    {
      code: "const x = <input type='range' />;",
      errors: [
        {
          messageId: "preferShadcn",
          data: { element: "input", replacement: "Slider", lowercase: "slider" },
        },
      ],
    },
    // Dynamic type falls back to the generic Input rather than a wrong primitive.
    {
      code: "const x = <input type={inputType} />;",
      errors: [
        {
          messageId: "preferShadcn",
          data: { element: "input", replacement: "Input", lowercase: "input" },
        },
      ],
    },
    {
      code: "const x = <select><option value='a'>a</option></select>;",
      errors: [{ messageId: "preferShadcn" }],
    },
    {
      code: "const x = <textarea rows={4} />;",
      errors: [{ messageId: "preferShadcn" }],
    },
    {
      code: "const x = <dialog open>hi</dialog>;",
      errors: [{ messageId: "preferShadcn" }],
    },
  ],
});
