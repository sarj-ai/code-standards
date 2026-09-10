import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION,
} from "../../src/rules/no-redundant-optional-array-default.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});
const PRODUCTION = "src/schema.ts";

RULE_TESTER.run("no-redundant-optional-array-default", rule, {
  valid: [
    {
      name: "accepts the documented array default",
      filename: PRODUCTION,
      code: NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "does not touch string defaults",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Name = z.string().optional().default("");',
    },
    {
      name: "does not touch scalar defaults",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Count = z.number().optional().default(0);',
    },
    {
      name: "preserves a semantically distinct outer optional",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).default([]).optional();',
    },
    {
      name: "allows an array default without optional",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).default([]);',
    },
    {
      name: "allows an optional array without a default",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).optional();',
    },
    {
      name: "does not infer through a schema alias",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Base = z.array(z.string()); const Items = Base.optional().default([]);',
    },
    {
      name: "preserves comments around the optional wrapper",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()) /* keep this context */.optional().default([]);',
    },
    {
      name: "ignores a same-shaped local API",
      filename: PRODUCTION,
      code: 'const z = toolkit; const Items = z.array(z.string()).optional().default([]);',
    },
    {
      name: "ignores a same-shaped non-Zod import",
      filename: PRODUCTION,
      code: 'import { z } from "./schema-kit.js"; const Items = z.array(z.string()).optional().default([]);',
    },
    {
      name: "ignores a shadowed Zod namespace",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; function build(z: SchemaKit) { return z.array(z.string()).optional().default([]); }',
    },
    {
      name: "ignores test files",
      filename: "src/schema.test.ts",
      code: NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION.examples[1].files[0].source,
    },
    {
      name: "ignores generated files",
      filename: "src/generated/schema.ts",
      code: NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION.examples[1].files[0].source,
    },
  ],
  invalid: [
    {
      name: "reports and fixes the documented redundant optional",
      filename: PRODUCTION,
      code: NO_REDUNDANT_OPTIONAL_ARRAY_DEFAULT_DOCUMENTATION.examples[1].files[0].source,
      output: 'import { z } from "zod"; const Items = z.array(z.string()).default([]);',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "supports array method syntax",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.string().array().optional().default([]);',
      output: 'import { z } from "zod"; const Items = z.string().array().default([]);',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "supports lazy array defaults",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).optional().default(() => []);',
      output: 'import { z } from "zod"; const Items = z.array(z.string()).default(() => []);',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "resolves an aliased namespace import",
      filename: PRODUCTION,
      code: 'import { z as schema } from "zod/v4"; const Items = schema.array(schema.string()).optional().default([]);',
      output: 'import { z as schema } from "zod/v4"; const Items = schema.array(schema.string()).default([]);',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "resolves an aliased named array constructor",
      filename: PRODUCTION,
      code: 'import { array as list, string } from "zod"; const Items = list(string()).optional().default([]);',
      output: 'import { array as list, string } from "zod"; const Items = list(string()).default([]);',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "finds the pair below an outer metadata method",
      filename: PRODUCTION,
      code: 'import * as schema from "zod"; const Items = schema.array(schema.string()).optional().default([]).describe("items");',
      output: 'import * as schema from "zod"; const Items = schema.array(schema.string()).default([]).describe("items");',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
  ],
});
