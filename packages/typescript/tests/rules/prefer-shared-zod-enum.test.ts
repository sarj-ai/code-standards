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
    PREFER_SHARED_ZOD_ENUM_DOCUMENTATION.examples[0].files[0].source,
    "const z = builder; z.enum(['a', 'b']); z.enum(['a', 'b']);",
    "import { z } from 'zod'; z.enum(values); z.enum(values);",
    "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['b', 'a']);",
    "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['a', 'c']);",
    { filename: "src/schema.test.ts", code: "import { z } from 'zod'; z.enum(['a', 'b']); z.enum(['a', 'b']);" },
  ],
  invalid: [
    {
      code: PREFER_SHARED_ZOD_ENUM_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "shareEnumDomain" }],
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
      code: "import { z } from 'zod'; const JobSchema = z.object({ provider: z.enum(['agy', 'claude', 'sol']).optional() });",
      errors: [{ messageId: "shareEnumDomain" }],
    },
  ],
});
