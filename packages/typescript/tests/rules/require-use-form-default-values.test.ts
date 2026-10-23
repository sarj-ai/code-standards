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
    { name: "keeps a replaced control's initialized contract", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); const initialized = useForm({ defaultValues: { name: '' } }); form.control = initialized.control; <Controller control={form.control} name='name' />;" },
    { name: "keeps a control replaced through an alias", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); const alias = form; alias.control = initialized; <Controller control={form.control} />;" },
    { name: "keeps a control replaced through an erased wrapper", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); (form as Custom)['control'] = initialized; <Controller control={form.control} />;" },
    { name: "keeps a control replaced through a destructuring target", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); ({ control: form.control } = initialized); <Controller control={form.control} />;" },
    { name: "keeps a control replaced through a defaulted array target", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); [form.control = initialized] = controls; <Controller control={form.control} />;" },
    { name: "keeps a deleted control", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); delete form.control; <Controller control={form.control} />;" },
    { name: "keeps controls written by loop targets", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); for (form.control of controls) {} <Controller control={form.control} />;" },
    { name: "keeps controls exposed to unknown helpers", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); configure(form); <Controller control={form.control} />;" },
    { name: "keeps controls exposed through native object alias methods", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); const alias = form.valueOf(); alias.control = initialized; <Controller control={form.control} />;" },
    { name: "keeps directly exported forms", code: "import { Controller, useForm } from 'react-hook-form'; export const form = useForm(); <Controller control={form.control} />;" },
    { name: "keeps forms exported through specifiers", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); export { form }; <Controller control={form.control} />;" },
    { name: "keeps a form with two distinct initializer sites outside the proof", code: "import { Controller, useForm } from 'react-hook-form'; function View() { var form = useForm(); var form = useForm({ defaultValues: {} }); return <Controller control={form.control} />; }" },
    { name: "keeps a control with two distinct initializer sites outside the proof", code: "import { Controller, useForm } from 'react-hook-form'; function View() { var { control } = useForm(); var { control } = useForm({ defaultValues: {} }); return <Controller control={control} />; }" },
    { name: "keeps reassigned imports outside native provenance", code: "import { Controller, useForm } from 'react-hook-form'; useForm = custom; const form = useForm(); <Controller control={form.control} />;" },
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
    { name: "retains form type queries and read-only member uses", code: "import { Controller, useForm } from 'react-hook-form'; const form = useForm(); type Form = typeof form; type Control = typeof form.control; form.getValues(); <Controller control={form.control} />;", errors: [{ messageId: "requireUseFormDefaultValues" }] },
    { name: "recognizes decoded module specifiers", code: "import { Controller, useForm } from 'react-\\u0068ook-form'; const form = useForm(); <Controller control={form.control} />;", errors: [{ messageId: "requireUseFormDefaultValues" }] },
    { name: "retains a single initializer with a later bare declaration", code: "import { Controller, useForm } from 'react-hook-form'; function View() { var form = useForm(); var form; return <Controller control={form.control} />; }", errors: [{ messageId: "requireUseFormDefaultValues" }] },
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
