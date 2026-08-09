import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { requireZodFormValidationDocumentation } from "../../src/rules/require-zod-form-validation.js";

// Bind vitest to RuleTester for proper test reporting
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("require-zod-form-validation", rule, {
  valid: [
    { name: "accepts the documented validated value", code: requireZodFormValidationDocumentation.examples[0].files[0].source },
    {
      name: "ignores FormData reads in test files",
      code: "async function t(request) { const formData = await request.formData(); expect(formData.get('a')).toBe('1'); }",
      filename: "/repo/packages/x/__tests__/dom/data-browser-router-test.tsx",
    },
    {
      name: "accepts inline parse with a Z-prefixed schema",
      code: "const name = ZUser.parse({ name: formData.get('name') });",
    },
    {
      name: "accepts inline safeParse",
      code: "const name = ZUser.safeParse({ name: formData.get('name') });",
    },
    {
      name: "accepts inline async parse methods",
      code: "const a = await ZUser.parseAsync(formData.get('a')); const b = await ZUser.safeParseAsync(formData.get('b'));",
    },
    {
      name: "accepts a Schema-suffixed receiver",
      code: "const name = userSchema.parse({ name: formData.get('name') });",
    },
    {
      name: "accepts a z builder chain",
      code: "const name = z.object({ name: z.string() }).parse({ name: formData.get('name') });",
    },
    {
      name: "accepts a nested read under parse",
      code: "const result = ZUser.parse({ inner: { name: formData.get('name') } });",
    },
    {
      name: "ignores get calls on non-form sources",
      code: "const name = req.body.get('name');",
    },
    {
      name: "ignores other FormData methods",
      code: "for (const key of formData.keys()) {}",
    },
    {
      name: "accepts a read nested in an argument under parse",
      code: "ZForm.parse(Object.fromEntries([['name', formData.get('name')]]));",
    },
    {
      name: "recognizes a binding initialized by an awaited formData call",
      code: "async function f(req) { const fd = await req.formData(); return ZUser.parse({ name: fd.get('name') }); }",
    },
    {
      name: "accepts a binding validated by safeParse later",
      code: "const tokenRaw = formData.get('t');\nconst parsedForm = SubmitFormDataSchema.safeParse({ t: typeof tokenRaw === 'string' ? tokenRaw : undefined });",
    },
    {
      name: "accepts a binding validated several statements later",
      code: "const emailRaw = formData.get('email');\ntrace('submit', { present: emailRaw !== null });\nconst parsed = ZSignup.parse({ email: emailRaw });",
    },
    {
      name: "tracks a type-asserted binding that is validated later",
      code: "const emailRaw = formData.get('email') as string;\nconst parsed = ZSignup.parse({ email: emailRaw });",
    },
    {
      name: "tracks a non-null asserted binding that is validated later",
      code: "const emailRaw = formData.get('email')!;\nconst parsed = ZSignup.parse({ email: emailRaw });",
    },
    {
      name: "accepts a File binding narrowed with instanceof",
      code: "const file = formData.get('file');\nif (!(file instanceof File)) { throw new Error('bad'); }\nawait upload(file);",
    },
    {
      name: "accepts an inline File narrowing",
      code: "if (formData.get('file') instanceof File) { ok(); }",
    },
    {
      name: "accepts a Blob binding narrowed with instanceof",
      code: "const blob = formData.get('blob');\nif (blob instanceof Blob) { await upload(blob); }",
    },
  ],
  invalid: [
    { name: "reports the documented raw value", code: requireZodFormValidationDocumentation.examples[1].files[0].source, errors: [{ messageId: "missingZodValidation" }] },
    {
      name: "reports a production action read",
      code: "export async function action(request) { const formData = await request.formData(); return save(formData.get('name')); }",
      filename: "/repo/src/app/actions.ts",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "reports a bare FormData read",
      code: "const name = formData.get('name');",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "reports a read inside an unrelated call",
      code: "console.log(formData.get('name'));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "does not mistake JSON.parse for Zod validation",
      code: "const name = JSON.parse(formData.get('name'));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "does not mistake Date.parse for Zod validation",
      code: "const ts = Date.parse(formData.get('createdAt'));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "reports an unvalidated binding initialized by formData",
      code: "async function f(req) { const fd = await req.formData(); return fd.get('name'); }",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "reports each unvalidated read",
      code: "const a = formData.get('a'); const b = formData.get('b');",
      errors: [
        { messageId: "missingZodValidation" },
        { messageId: "missingZodValidation" },
      ],
    },
    {
      name: "does not treat an ordinary binding use as validation",
      code: "const tokenRaw = formData.get('t');\nawait redeem(tokenRaw);",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "does not treat JSON.parse on a binding as validation",
      code: "const raw = formData.get('payload');\nconst data = JSON.parse(String(raw));",
      errors: [{ messageId: "missingZodValidation" }],
    },
    {
      name: "does not treat unrelated instanceof narrowing as validation",
      code: "const value = formData.get('value');\nif (value instanceof URL) { use(value); }",
      errors: [{ messageId: "missingZodValidation" }],
    },
  ],
});
