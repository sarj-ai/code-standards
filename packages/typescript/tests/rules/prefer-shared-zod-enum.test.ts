import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_SHARED_ZOD_ENUM_DOCUMENTATION } from "../../src/rules/prefer-shared-zod-enum.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, sourceType: "module" } });

RULE_TESTER.run("prefer-shared-zod-enum", rule, {
  valid: [
    { name: "does not treat shadowed Zod as an imported schema builder", code: "import { z } from 'zod'; function build(z) { return z.enum(['a', 'b']); }" },
    { name: "does not inherit imported namespace across nested blocks", code: "import * as schema from 'zod'; { const schema = otherBuilder; schema.enum(['a', 'b']); }" },
    PREFER_SHARED_ZOD_ENUM_DOCUMENTATION.examples[0].files[0].source,
    "const z = builder; z.enum(['a', 'b']); z.enum(['a', 'b']);",
    "import { z } from 'zod'; z.enum(values); z.enum(values);",
    "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });",
    "import { z } from 'zod'; function schema() { const LocalSchema = z.enum(['a', 'b']); return LocalSchema; }",
    "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['b', 'a']);",
    "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['a', 'c']);",
    { name: "preserves independently customized enum errors", code: "import { z } from 'zod'; z.enum(['a', 'b'], { error: 'first contract' }); z.enum(['a', 'b'], { error: 'second contract' });" },
    { filename: "src/schema.test.ts", code: "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['a', 'b']);" },
  ],
  invalid: [
    {
      code: PREFER_SHARED_ZOD_ENUM_DOCUMENTATION.examples[1].files[0].source,
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
  ],
});
