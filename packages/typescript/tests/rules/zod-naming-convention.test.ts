import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/zod-naming-convention.js";

// Bind vitest to RuleTester for proper test reporting
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester();

ruleTester.run("zod-naming-convention", rule, {
  valid: [
    // Direct z.object() with Z prefix
    { code: "const ZUser = z.object({ name: z.string() });" },
    // Chained z.object().extend() with Z prefix
    { code: "const ZUser = z.object({ name: z.string() }).extend({ age: z.number() });" },
    // Long chains with Z prefix
    {
      code: "const ZUser = z.object({ name: z.string() }).extend({ age: z.number() }).refine((d) => d.age > 0);",
    },
    // Non-Zod call expressions are ignored
    { code: "const user = createUser({ name: 'Alice' });" },
    // Non-CallExpression initializers are ignored
    { code: "const greeting = 'hello';" },
    // No initializer at all
    { code: "let unset;" },
    // z.literal — also Zod, with Z prefix
    { code: "const ZRole = z.literal('admin');" },
    // Member expression initializer that does not start with z
    { code: "const config = settings.values;" },
    // C-1 regression: the `XxxSchema` SUFFIX convention is equally valid and is
    // what `require-zod-form-validation` already accepts as a Zod schema. The
    // 42k-LOC adoption codebase uses it uniformly — 220 symbols, zero defects.
    { code: "const userSchema = z.object({ name: z.string() });" },
    { code: "const SubmitFormDataSchema = z.object({ t: z.string() });" },
    { code: "const RoleSchema = z.enum(['admin', 'user']);" },
    {
      code: "const userSchema = z.object({ name: z.string() }).extend({ age: z.number() });",
    },
    // Explicit prefix-only convention: `ZUser` conforms.
    {
      code: "const ZUser = z.object({ name: z.string() });",
      options: [{ convention: "prefix" }],
    },
    // Explicit suffix-only convention: `userSchema` conforms.
    {
      code: "const userSchema = z.object({ name: z.string() });",
      options: [{ convention: "suffix" }],
    },
  ],
  invalid: [
    // Direct z.object() matching neither convention.
    {
      code: "const User = z.object({ name: z.string() });",
      errors: [{ messageId: "zodSchemaName" }],
    },
    // Chained z.object().extend() matching neither convention.
    {
      code: "const User = z.object({ name: z.string() }).extend({ age: z.number() });",
      errors: [{ messageId: "zodSchemaName" }],
    },
    // Lowercase `z` prefix is not the prefix convention (needs `Z<Capital>`).
    {
      code: "const zUser = z.object({ name: z.string() });",
      errors: [{ messageId: "zodSchemaName" }],
    },
    // Even deeper chains still get flagged
    {
      code: "const User = z.object({}).extend({}).refine(() => true);",
      errors: [{ messageId: "zodSchemaName" }],
    },
    // z.enum() — schema, but wrong name
    {
      code: "const Role = z.enum(['admin', 'user']);",
      errors: [{ messageId: "zodSchemaName" }],
    },
    // A team pinned to the prefix convention still rejects the suffix form.
    {
      code: "const userSchema = z.object({ name: z.string() });",
      options: [{ convention: "prefix" }],
      errors: [{ messageId: "zPrefix" }],
    },
    // ...and vice versa.
    {
      code: "const ZUser = z.object({ name: z.string() });",
      options: [{ convention: "suffix" }],
      errors: [{ messageId: "schemaSuffix" }],
    },
  ],
});
