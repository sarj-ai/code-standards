/** @fileoverview require-use-form-default-values — the documentation and executable examples of `@sarj/require-use-form-default-values`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_USE_FORM_DEFAULT_VALUES_DOCUMENTATION = {
  summary: "Require explicit form-level initialization or a field default for directly bound Controller fields.",
  rationale: "React Hook Form exposes form-level defaultValues/values and field-level defaultValue as its explicit initialization mechanisms. A directly bound controlled field should not omit both mechanisms.",
  remediation: "Provide a non-undefined defaultValues or values option to useForm, or a non-undefined defaultValue on the associated Controller/useController field.",
  category: "correctness",
  limitations: [
    "The rule proves only that an explicit form-level initialization option or field default is present; it does not prove that a particular field path occurs inside a defaultValues/values object.",
    "The rule reports only scope-resolved Controller/useController fields explicitly bound to a directly created useForm control. FormProvider context, wrapper hooks, dynamic options, spreads, computed properties, and interprocedural flows are intentionally left unreported.",
    "Form bindings must have one initializer and remain local and read-only; aliases, exports, property writes, and other escaping uses are left unreported.",
  ],
  examples: [
    {
      id: "controlled-field-with-form-defaults",
      title: "Initialize controlled fields at form level",
      outcome: "no-match",
      files: [{ path: "profile-form.tsx", source: "'use client'; import { Controller, useForm } from 'react-hook-form'; function ProfileForm() { const form = useForm({ defaultValues: { name: '' } }); return <Controller control={form.control} name='name' render={() => null} />; }" }],
      focusPath: "profile-form.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "controlled-field-without-default",
      title: "Do not leave a controlled field uninitialized",
      outcome: "match",
      files: [{ path: "profile-form.tsx", source: "'use client'; import { Controller, useForm } from 'react-hook-form'; function ProfileForm() { const form = useForm(); return <Controller control={form.control} name='name' render={() => null} />; }" }],
      focusPath: "profile-form.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
