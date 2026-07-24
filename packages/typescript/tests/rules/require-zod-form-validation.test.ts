import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-zod-form-validation.js";

// Bind vitest to RuleTester for proper test reporting
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("require-zod-form-validation", rule, {
  valid: [
    // formData.get() wrapped in a Zod schema .parse() call
    {
      code: "const name = ZUser.parse({ name: formData.get('name') });",
    },
    // safeParse is a valid Zod validation too (regression: previously rejected).
    {
      code: "const name = ZUser.safeParse({ name: formData.get('name') });",
    },
    // Schema-suffixed receiver counts as a Zod schema.
    {
      code: "const name = userSchema.parse({ name: formData.get('name') });",
    },
    // `z.*` builder chain counts as a Zod schema.
    {
      code: "const name = z.object({ name: z.string() }).parse({ name: formData.get('name') });",
    },
    // Nested: .parse() ancestor exists somewhere above
    {
      code: "const result = ZUser.parse({ inner: { name: formData.get('name') } });",
    },
    // Reading from a different identifier that isn't a form source
    {
      code: "const name = req.body.get('name');",
    },
    // Non-`.get()` member call on formData — rule only targets `.get(...)`
    {
      code: "for (const key of formData.keys()) {}",
    },
    // .parse() ancestor at the top level expression
    {
      code: "ZForm.parse(Object.fromEntries([['name', formData.get('name')]]));",
    },
    // Un-hardcoded receiver: a binding from `.formData()`, validated via Zod.
    {
      code: "async function f(req) { const fd = await req.formData(); return ZUser.parse({ name: fd.get('name') }); }",
    },
    // FP-6: validation happens ONE HOP later, through a binding. Walking up from
    // the `.get()` call cannot see it; tracking the binding through scope can.
    {
      code: "const tokenRaw = formData.get('t');\nconst parsedForm = SubmitFormDataSchema.safeParse({ t: typeof tokenRaw === 'string' ? tokenRaw : undefined });",
    },
    // FP-6: several statements later, and via the `Z`-prefix convention.
    {
      code: "const emailRaw = formData.get('email');\ntrace('submit', { present: emailRaw !== null });\nconst parsed = ZSignup.parse({ email: emailRaw });",
    },
    // FP-6: a file upload narrowed by `instanceof File` — Zod has nothing
    // useful to say about a `File`, and `instanceof` IS the validation.
    {
      code: "const file = formData.get('file');\nif (!(file instanceof File)) { throw new Error('bad'); }\nawait upload(file);",
    },
    // FP-6: the same narrowing written inline.
    {
      code: "if (formData.get('file') instanceof File) { ok(); }",
    },
  ],
  invalid: [
    // Bare formData.get() with no Zod validation
    {
      code: "const name = formData.get('name');",
      errors: [{ messageId: "missingZodValidation" }],
    },
    // formData.get() inside an unrelated function call
    {
      code: "console.log(formData.get('name'));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    // JSON.parse is NOT Zod validation — must still be flagged (false-negative fix).
    {
      code: "const name = JSON.parse(formData.get('name'));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    // Date.parse is NOT Zod validation either.
    {
      code: "const ts = Date.parse(formData.get('createdAt'));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    // Un-hardcoded receiver: a binding from `.formData()` with no validation.
    {
      code: "async function f(req) { const fd = await req.formData(); return fd.get('name'); }",
      errors: [{ messageId: "missingZodValidation" }],
    },
    // Multiple unvalidated reads — each is flagged
    {
      code: "const a = formData.get('a'); const b = formData.get('b');",
      errors: [
        { messageId: "missingZodValidation" },
        { messageId: "missingZodValidation" },
      ],
    },
    // FP-6 must not over-suppress: a binding that is USED but never validated
    // is still an unvalidated read.
    {
      code: "const tokenRaw = formData.get('t');\nawait redeem(tokenRaw);",
      errors: [{ messageId: "missingZodValidation" }],
    },
    // FP-6 must not over-suppress: `JSON.parse` on the binding is not Zod.
    {
      code: "const raw = formData.get('payload');\nconst data = JSON.parse(String(raw));",
      errors: [{ messageId: "missingZodValidation" }],
    },
  ],
});
