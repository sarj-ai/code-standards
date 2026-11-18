// vitest: shared-module-graph
import rule from "../../src/rules/prefer-zod-field-bounds.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

TESTER.run("prefer-zod-field-bounds", rule, {
  valid: [
    {
      name: "declarative field bound",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int().min(1) });",
    },
    {
      name: "cross-field invariant",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= row.other);",
    },
    {
      name: "floating point field",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number() }).refine(row => row.value >= 1);",
    },
    {
      name: "fractional threshold",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1.5);",
    },
    {
      name: "unsafe threshold",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 9007199254740992);",
    },
    {
      name: "redundant intrinsic minimum",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= -9007199254740991);",
    },
    {
      name: "empty intrinsic domain",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value > 9007199254740991);",
    },
    {
      name: "dynamic threshold",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= MINIMUM);",
    },
    {
      name: "compound invariant",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1 && row.value <= 10);",
    },
    {
      name: "block callback",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => { return row.value >= 1; });",
    },
    {
      name: "async callback",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(async row => row.value >= 1);",
    },
    {
      name: "second callback parameter",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine((row, context) => row.value >= 1);",
    },
    {
      name: "destructured callback",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(({ value }) => value >= 1);",
    },
    {
      name: "defaulted callback argument",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine((row = fallback) => row.value >= 1);",
    },
    {
      name: "predicate side effect",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => check(row.value));",
    },
    {
      name: "computed field read",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row['value'] >= 1);",
    },
    {
      name: "custom error options",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1, { path: ['value'] });",
    },
    {
      name: "default target",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int().default(1) }).refine(row => row.value >= 1);",
    },
    {
      name: "transformed target",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int().transform(normalize) }).refine(row => row.value >= 1);",
    },
    {
      name: "branded target",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int().brand() }).refine(row => row.value >= 1);",
    },
    {
      name: "existing target bound",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int().min(0) }).refine(row => row.value >= 1);",
    },
    {
      name: "coerced target",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.coerce.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "custom integer error",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int({ error: custom }) }).refine(row => row.value >= 1);",
    },
    {
      name: "opaque shape",
      code: "import { z } from 'zod'; const CountSchema = z.object(shape).refine(row => row.value >= 1);",
    },
    {
      name: "spread shape",
      code: "import { z } from 'zod'; const CountSchema = z.object({ ...fields, value: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "computed shape key",
      code: "import { z } from 'zod'; const CountSchema = z.object({ [name]: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "duplicate shape key",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.string(), value: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "getter shape",
      code: "import { z } from 'zod'; const CountSchema = z.object({ get value() { return z.number().int(); } }).refine(row => row.value >= 1);",
    },
    {
      name: "prototype setter key",
      code: "import { z } from 'zod'; const CountSchema = z.object({ __proto__: z.number().int() }).refine(row => row.__proto__ >= 1);",
    },
    {
      name: "opaque sibling",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int(), other: OtherSchema }).refine(row => row.value >= 1);",
    },
    {
      name: "default sibling",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int(), label: z.string().default('') }).refine(row => row.value >= 1);",
    },
    {
      name: "schema wrapper",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1).brand();",
    },
    {
      name: "opaque enclosing call",
      code: "import { z } from 'zod'; const CountSchema = consume(z.object({ value: z.number().int() }).refine(row => row.value >= 1));",
    },
    {
      name: "mini is another API",
      code: "import { z } from 'zod/mini'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "v3 is another API",
      code: "import { z } from 'zod/v3'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "local names do not prove Zod",
      code: "import { z } from './zod.js'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "type-only namespace",
      code: "import type { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
    },
    {
      name: "shadowed provider",
      code: "import { z } from 'zod'; function make(z) { return z.object({ value: z.number().int() }).refine(row => row.value >= 1); }",
    },
    {
      name: "visible namespace mutation",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1); z.object = other;",
    },
    {
      name: "namespace escape",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1); customize(z);",
    },
    {
      name: "limit owned by integer policy",
      code: "import { z } from 'zod'; const CountSchema = z.object({ limit: z.number().int() }).refine(row => row.limit >= 1);",
    },
    {
      name: "version owned by integer policy",
      code: "import { z } from 'zod'; const CountSchema = z.object({ version: z.number().int() }).refine(row => row.version >= 1);",
    },
    {
      name: "scalar refinement remains separate",
      code: "import { z } from 'zod'; const CountSchema = z.number().int().refine(value => value >= 1);",
    },
    {
      name: "named schema remains opaque",
      code: "import { z } from 'zod'; const CountSchema = BaseSchema.refine(row => row.value >= 1);",
    },
    {
      name: "generated output",
      filename: "src/count.generated.ts",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
    },
  ],
  invalid: [
    {
      name: "simple lower bound",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "exclusive lower bound",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value > 0);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "upper bound",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value <= 100);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "exclusive upper bound",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value < 100);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "reversed comparison",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => 1 <= row.value);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "signed literal",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= -4);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "positive sign",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= +4);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "primitive siblings",
      code: "import { z } from 'zod'; const CountSchema = z.object({ label: z.string(), value: z.number().int(), enabled: z.boolean() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "namespace alias",
      code: "import * as schema from 'zod'; const CountSchema = schema.object({ value: schema.number().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "named constructors",
      code: "import { object as record, number as numeric } from 'zod/v4'; const CountSchema = record({ value: numeric().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "named provider alias",
      code: "import { z as schema } from 'zod'; const CountSchema = schema.object({ value: schema.number().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "exported schema",
      code: "import { z } from 'zod'; export const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "quoted shape key",
      code: "import { z } from 'zod'; const CountSchema = z.object({ 'value': z.number().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "one warning per refinement",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 2);",
      errors: [{ messageId: "fieldBounds" }],
    },
    {
      name: "maintained tests are checked",
      filename: "tests/count.test.ts",
      code: "import { z } from 'zod'; const CountSchema = z.object({ value: z.number().int() }).refine(row => row.value >= 1);",
      errors: [{ messageId: "fieldBounds" }],
    },
  ],
});
