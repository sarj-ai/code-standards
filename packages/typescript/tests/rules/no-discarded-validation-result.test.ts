// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION } from "../../src/rules/no-discarded-validation-result.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });
TESTER.run("no-discarded-validation-result", rule, {
  valid: [
    NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION.examples[1].files[0].source,
    "import { z } from 'zod'; z.string().parse(raw);",
    "import { z } from 'zod'; const Schema = z.object({ trim: z.string() }); Schema.shape.trim.parse(raw);",
    "import { z } from 'zod'; const Schema = z.object({ default: z.string() }); Schema.shape.default.parse(raw);",
    "import { z } from 'zod'; const result = z.string().safeParse(raw); consume(result);",
    "import { z } from './custom.js'; z.string().trim().parse(raw);",
    "import { z } from 'zod'; function run(z) { z.string().trim().parse(raw); }",
    "import { z } from 'zod'; let Schema = z.string().trim(); Schema = custom; Schema.parse(raw);",
  ],
  invalid: [
    NO_DISCARDED_VALIDATION_RESULT_DOCUMENTATION.examples[0].files[0].source,
    "import { z } from 'zod'; z.union([z.string().trim(), z.number()]).parse(raw);",
    "import { coerce } from 'zod'; coerce.number().parse(raw);",
    "import { z } from 'zod'; z.string().safeParse(raw);",
    "import * as z from 'zod'; const Schema = z.object({ name: z.string().default('name') }); Schema.parse(raw);",
    "import { z as schema } from 'zod'; async function run() { await schema.coerce.number().parseAsync(raw); }",
    "import { z } from 'zod'; async function run() { await z.string().safeParseAsync(raw); }",
  ].map(code => ({ code, errors: [{ messageId: "discarded" as const }] })),
});
