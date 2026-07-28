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
    // shadcn primitives — the prescribed components.
    { code: "const x = <Input value='' onChange={() => {}} />;" },
    { code: "const x = <Select><option /></Select>;" },
    { code: "const x = <Textarea />;" },
    { code: "const x = <Dialog open />;" },
    { code: "const x = <Button>Click</Button>;" },
    // Ignore <input type="hidden">
    { code: "const x = <input type='hidden' value='secret' />;" },
    // Ignore components/ui/*
    {
      code: "const x = <button type='button'>click</button>;",
      filename: "/Users/nasrmaswood/code/components/ui/button.tsx"
    },
    // Ignore email paths
    {
      code: "const x = <button type='button'>click</button>;",
      filename: "/Users/nasrmaswood/code/emails/welcome.tsx"
    },
    // Non-form elements are unrelated.
    { code: "const x = <div className='wrapper' />;" },
  ],
  invalid: [
    {
      code: "const x = <input type='text' />;",
      errors: [{ messageId: "preferShadcn" }],
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
    {
      code: "const x = <button>Submit</button>;",
      errors: [{ messageId: "preferShadcn" }],
    },
  ],
});
