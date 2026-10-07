// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-use-form-default-values.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { ecmaFeatures: { jsx: true }, sourceType: "module" } } });

RULE_TESTER.run("require-use-form-default-values", rule, {
  valid: [
    "import { useForm } from 'react-hook-form'; useForm();",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ ...options }); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm(options); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm(...options); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ [key]: options }); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ values: current }); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: { name: '' } }); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: undefined, defaultValues: { name: '' } }); <Controller control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); <Controller control={form.control} defaultValue='' name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); <Controller control={form.control} defaultValue={undefined} defaultValue='' name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); <Controller {...props} control={form.control} name='name' />;",
    "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); <Controller name='name' />;",
    "import { Controller, useForm } from './forms'; const form = useForm(); <Controller control={form.control} />;",
    "import { Controller, useForm } from 'react-hook-form'; function inner(Controller) { const form = useForm(); return <Controller control={form.control} />; }",
    "import { useController, useForm } from 'react-hook-form'; const form = useForm(); useController({ control: form.control, defaultValue: '' });",
    "import { useController, useForm } from 'react-hook-form'; const form = useForm(); useController({ ...field, control: form.control });",
    "import { useController, useForm } from 'react-hook-form'; const form = useForm(); useController(fieldOptions);",
    "import { Controller, useForm } from 'react-hook-form'; let form = useForm(); form = replacement; <Controller control={form.control} />;",
  ],
  invalid: [
    {
      name: "reports a Controller bound to an uninitialized form",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); <Controller control={form.control} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "reports aliased imports and destructured control",
      code: "import { Controller as Field, useForm as makeForm } from 'react-hook-form'; const { control } = makeForm({ mode: 'onChange' }); <Field control={control} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "reports useController bound to an uninitialized form",
      code: "import { useController, useForm } from 'react-hook-form'; const form = useForm(); useController({ name: 'name', control: form.control });",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "treats explicit undefined form and field defaults as missing",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: undefined }); <Controller control={form.control} defaultValue={void 0} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "unwraps TypeScript assertions around undefined defaults",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: undefined as unknown }); <Controller control={form.control} defaultValue={(undefined as unknown)!} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "unwraps satisfies expressions around undefined defaults",
      code: "import { useController, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: undefined satisfies unknown }); useController({ control: form.control, defaultValue: undefined satisfies unknown });",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "unwraps angle-bracket assertions around undefined defaults",
      filename: "/repo/form.ts",
      code: "import { useController, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: <undefined>undefined }); useController({ control: form.control, defaultValue: <undefined>undefined });",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "uses the last duplicate form default",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm({ defaultValues: { name: '' }, defaultValues: undefined }); <Controller control={form.control} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "uses the last duplicate field default",
      code: "import { useController, useForm } from 'react-hook-form'; const form = useForm(); useController({ control: form.control, defaultValue: '', defaultValue: undefined });",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "uses the last duplicate JSX field default",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); <Controller control={form.control} defaultValue='' defaultValue={undefined} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "tracks a control extracted from a form object",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); const control = form.control; <Controller control={control} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
    {
      name: "tracks an aliased control destructured from a form object",
      code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); const { control: fieldControl } = form; <Controller control={fieldControl} name='name' />;",
      errors: [{ messageId: "requireUseFormDefaultValues" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "controlled-field-without-default-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "profile-form.tsx",
    "expectedCount": 1,
    "files": [
      {
        "path": "profile-form.tsx",
        "source": "'use client'; import { Controller, useForm } from 'react-hook-form'; function ProfileForm() { const form = useForm(); return <Controller control={form[\"control\"]} name='name' render={() => null} />; }"
      }
    ]
  },
  {
    "id": "controlled-field-without-default-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "profile-form.tsx",
    "expectedCount": 0,
    "files": [
      {
        "path": "profile-form.tsx",
        "source": "'use client'; import { Controller, useForm } from 'react-hook-form'; function ProfileForm() { const form = useForm(); return <Controller control={form[auditDynamicMember]} name='name' render={() => null} />; }"
      }
    ]
  }
] } });
});
