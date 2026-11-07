// vitest: shared-module-graph
import rule from "../../src/rules/no-discarded-validation-result.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

const LOST_TRANSFORM_EXAMPLE = "import { z } from 'zod'; z.string().trim().parse(raw);";
const USED_TRANSFORM_EXAMPLE = "import { z } from 'zod'; function parse(raw: unknown) { return z.string().trim().parse(raw); }";

TESTER.run("no-discarded-validation-result", rule, {
  valid: [
    USED_TRANSFORM_EXAMPLE,
    "import { z } from 'zod'; z.string().parse(raw);",
    "import { z } from 'zod'; const Schema = z.object({ trim: z.string() }); Schema.shape.trim.parse(raw);",
    "import { z } from 'zod'; const Schema = z.object({ default: z.string() }); Schema.shape.default.parse(raw);",
    "import { z } from 'zod'; const result = z.string().safeParse(raw); consume(result);",
    "import { z } from './custom.js'; z.string().trim().parse(raw);",
    "import { z } from 'zod'; function run(z) { z.string().trim().parse(raw); }",
    "import { z } from 'zod'; let Schema = z.string().trim(); Schema = custom; Schema.parse(raw);",
  ],
  invalid: [
    LOST_TRANSFORM_EXAMPLE,
    "import { z } from 'zod'; z.union([z.string().trim(), z.number()]).parse(raw);",
    "import { coerce } from 'zod'; coerce.number().parse(raw);",
    "import { z } from 'zod'; z.string().safeParse(raw);",
    "import * as z from 'zod'; const Schema = z.object({ name: z.string().default('name') }); Schema.parse(raw);",
    "import { z as schema } from 'zod'; async function run() { await schema.coerce.number().parseAsync(raw); }",
    "import { z } from 'zod'; async function run() { await z.string().safeParseAsync(raw); }",
  ].map(code => ({ code, errors: [{ messageId: "discarded" as const }] })),
});
