// vitest: shared-module-graph
import rule from "../../src/rules/prefer-shared-zod-enum.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("prefer-shared-zod-enum", rule, {
  valid: [
    { name: "does not close an externally supplied value domain", code: "import { z } from 'zod'; declare const externalValues: readonly [string, ...string[]]; z.enum([...externalValues]); z.enum([...externalValues]);" },
    { name: "does not infer a finite version domain from defaults", code: "import { z } from 'zod'; const first = z.string().default('dev'); const second = z.string().default('dev');" },
    { name: "keeps finite and flexible version contracts independent", code: "import { z } from 'zod'; const channel = z.enum(['dev', 'stable']); const version = z.string().default('dev');" },
    { name: "keeps interpolated enum domains opaque", code: 'import { z } from "zod"; z.enum([`a${suffix}`, `b`]); z.enum([`a${suffix}`, `b`]);' },
    { name: "preserves domain order through erased literals", code: 'import { z } from "zod"; z.enum([("a" as const), ("b" as const)]); z.enum([("b" as const), ("a" as const)]);' },
    { name: "preserves customized errors through erased literals", code: 'import { z } from "zod"; z.enum([("a" as const), ("b" as const)], {error: "first"}); z.enum([("a" as const), ("b" as const)], {error: "second"});' },

    { name: "does not treat shadowed Zod as an imported schema builder", code: "import { z } from 'zod'; function build(z) { return z.enum(['a', 'b']); }" },
    { name: "does not inherit imported namespace across nested blocks", code: "import * as schema from 'zod'; { const schema = otherBuilder; schema.enum(['a', 'b']); }" },
    "import { z } from 'zod'; const ProviderSchema = z.enum(['agy', 'claude', 'sol']); const JobSchema = z.object({ provider: ProviderSchema }); const StatusSchema = z.object({ provider: ProviderSchema.optional() });",
    "const z = builder; z.enum(['a', 'b']); z.enum(['a', 'b']);",
    "import { z } from 'zod'; z.enum(values); z.enum(values);",
    "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });",
    "import { z } from 'zod'; function schema() { const LocalSchema = z.enum(['a', 'b']); return LocalSchema; }",
    "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['b', 'a']);",
    "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['a', 'c']);",
    { name: "preserves independently customized enum errors", code: "import { z } from 'zod'; z.enum(['a', 'b'], { error: 'first contract' }); z.enum(['a', 'b'], { error: 'second contract' });" },
    { filename: "src/schema.test.ts", code: "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['a', 'b']);" },
    { name: "inline-provider-dynamic-member", filename: "src/provider.ts", code: "import { z } from 'zod'; const JobSchema = z[auditDynamicMember]({ provider: z[auditDynamicMember](['agy', 'claude', 'sol']) }); const StatusSchema = z[auditDynamicMember]({ provider: z[auditDynamicMember](['agy', 'claude', 'sol'])[auditDynamicMember]() });" },
  ],
  invalid: [
    { name: "recognizes repeated no-substitution template enum domains", code: 'import { z } from "zod"; const FirstSchema = z.enum([`a`, `b`]); const SecondSchema = z.enum([`a`, `b`]);', errors: [{ messageId: "shareEnumDomain" }] },
    { name: "recognizes repeated enum domains through const assertions", code: 'import { z } from "zod"; const FirstSchema = z.enum([("a" as const), ("b" as const)]); const SecondSchema = z.enum([("a" as const), ("b" as const)]);', errors: [{ messageId: "shareEnumDomain" }] },
    { name: "recognizes a const assertion around a literal enum array", code: 'import { z } from "zod"; const FirstSchema = z.enum(["a", "b"] as const); const SecondSchema = z.enum([`a`, `b`]);', errors: [{ messageId: "shareEnumDomain" }] },

    {
      code: "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']) }); const StatusSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });",
      errors: [{ messageId: "shareEnumDomain" }, { messageId: "shareEnumDomain" }],
    },
    {
      code: "import * as schema from 'zod'; const FirstSchema = schema.enum(['a', 'b']); const SecondSchema = schema.enum(['a', 'b']); const ThirdSchema = schema.enum(['a', 'b']);",
      errors: [{ messageId: "shareEnumDomain" }, { messageId: "shareEnumDomain" }],
    },
    {
      code: "import { z as schema } from 'zod/v4'; const FirstSchema = schema.enum(['a', 'b']); const SecondSchema = schema.enum(['a', 'b']);",
      errors: [{ messageId: "shareEnumDomain" }],
    },
    {
      name: "reports only inline duplicates when a named schema already owns the domain",
      code: "import { z } from 'zod'; const DomainSchema = z.enum(['a', 'b']); const First = z.object({ value: z.enum(['a', 'b']) }); const Second = z.enum(['a', 'b']).optional();",
      errors: [{ messageId: "shareEnumDomain" }, { messageId: "shareEnumDomain" }],
    },
    { name: "inline-provider-static-member", filename: "src/provider.ts", code: "import { z } from 'zod'; const JobSchema = z[\"object\"]({ provider: z[\"enum\"](['agy', 'claude', 'sol']) }); const StatusSchema = z[\"object\"]({ provider: z[\"enum\"](['agy', 'claude', 'sol'])[\"optional\"]() });", errors: [{ messageId: "shareEnumDomain" }, { messageId: "shareEnumDomain" }] },
  ],
});
