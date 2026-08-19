import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-use-form-default-values.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("require-use-form-default-values", rule, {
  valid: [
    "import { useForm } from 'react-hook-form'; useForm({ defaultValues: { name: '' } });",
    "import { useForm as makeForm } from 'react-hook-form'; makeForm({ 'defaultValues': defaults });",
    "import { useForm } from './forms'; useForm();",
    "import { useForm } from 'react-hook-form'; function inner(useForm: () => void) { useForm(); }",
    "import { useForm } from 'react-hook-form'; const options = getOptions(); useForm(options);",
  ],
  invalid: [
    {
      code: "import { useForm } from 'react-hook-form'; useForm();",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      code: "import { useForm as makeForm } from 'react-hook-form'; makeForm({ mode: 'onChange' });",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
  ],
});
