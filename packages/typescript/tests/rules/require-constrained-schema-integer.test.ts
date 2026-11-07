// vitest: shared-module-graph
import rule from "../../src/rules/require-constrained-schema-integer.js";
import { ruleTester } from "./_tester.js";

const TESTER = ruleTester();

const UNCONSTRAINED_LIMIT_EXAMPLE = "import { z } from 'zod'; const OptionsSchema = z.object({ limit: z.number() });";
const CONSTRAINED_FIELDS_EXAMPLE =
  "import { z } from 'zod'; const OptionsSchema = z.object({ limit: z.number().int().positive(), version: z.int().nonnegative() });";

TESTER.run("require-constrained-schema-integer", rule, {
  valid: [
    CONSTRAINED_FIELDS_EXAMPLE,
    { name: "unrelated numeric domain", code: "import { z } from 'zod'; const S = z.object({ temperature: z.number() });" },
    { name: "named domain", code: "import { z } from 'zod'; const S = z.object({ limit: LimitSchema });" },
    { name: "different validation provider", code: "import { z } from './schema.js'; const S = z.object({ limit: z.number() });" },
    { name: "shadowed provider", code: "import { z } from 'zod'; function f(z) { return z.object({ limit: z.number() }); }" },
    { name: "string version domain", code: "import { z } from 'zod'; const S = z.object({ version: z.string() });" },
    { name: "version zero origin", code: "import { z } from 'zod'; const S = z.object({ version: z.number().int().min(0) });" },
    { name: "explicit named lower bound", code: "import { z } from 'zod'; const S = z.object({ limit: z.number().int().min(MINIMUM_LIMIT) });" },
    { name: "transform owns domain", code: "import { z } from 'zod'; const S = z.object({ limit: z.number().transform(decodeLimit) });" },
    { name: "generated artifact", filename: "src/options.generated.ts", code: UNCONSTRAINED_LIMIT_EXAMPLE },
  ],
  invalid: [
    { code: UNCONSTRAINED_LIMIT_EXAMPLE, errors: [{ messageId: "constrainInteger" }] },
    ...[
      ["unbounded integer", "import { z } from 'zod'; const S = z.object({ version: z.int() });"],
      ["fractional positive", "import { z } from 'zod'; const S = z.object({ limit: z.number().positive() });"],
      ["zero limit", "import { z } from 'zod'; const S = z.object({ limit: z.number().int().nonnegative() });"],
      ["negative version", "import { z } from 'zod'; const S = z.object({ version: z.int().min(-1) });"],
      ["upper bound only", "import { z } from 'zod'; const S = z.object({ version: z.number().int().max(100) });"],
      ["default without validation", "import { z } from 'zod'; const S = z.strictObject({ version: z.number().default(1) });"],
      ["coercion needs domain", "import { z } from 'zod'; const S = z.object({ limit: z.coerce.number() });"],
      ["aliased provider", "import { z as schema } from 'zod'; const S = schema.object({ limit: schema.number() });"],
      ["named factory", "import { object, number } from 'zod'; const S = object({ limit: number() });"],
      ["quoted field", "import { z } from 'zod'; const S = z.object({ 'limit': z.number() });"],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "constrainInteger" as const }] })),
  ],
});
