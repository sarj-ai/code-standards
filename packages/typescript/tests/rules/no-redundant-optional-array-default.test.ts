// vitest: shared-module-graph
import rule from "../../src/rules/no-redundant-optional-array-default.js";
import { ruleTester } from "./_tester.js";

const DOCUMENTED_ARRAY_DEFAULT = 'import { z } from "zod"; const Items = z.array(z.string()).default([]);';
const DOCUMENTED_OPTIONAL_ARRAY_DEFAULT = 'import { z } from "zod"; const Items = z.array(z.string()).optional().default([]);';

const RULE_TESTER = ruleTester();
const PRODUCTION = "src/schema.ts";

RULE_TESTER.run("no-redundant-optional-array-default", rule, {
  valid: [
    {
      name: "preserves a relative builder whose directory name ends in zod",
      filename: PRODUCTION,
      code: 'import { z } from "./my-zod/index.js"; const Items = z.array(z.string()).optional().default([]);',
    },
    {
      name: "preserves an unrelated scoped Zod integration package",
      filename: PRODUCTION,
      code: 'import { z } from "@hono/zod-validator"; const Items = z.array(z.string()).optional().default([]);',
    },
    {
      name: "preserves unvalidated data returned by a typed fallback",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const fallback = (): string[] => JSON.parse("{}").missing; const Items = z.array(z.string()).optional().default(fallback);',
    },
    {
      name: "preserves an async fallback",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).optional().default(async () => []);',
    },
    {
      name: "preserves a generator fallback",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).optional().default(function* () { yield []; });',
    },
    {
      name: "preserves a Zod 3 fallback returning undefined",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default(() => undefined);',
    },
    {
      name: "preserves an opaque fallback function",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).optional().default(fallback);',
    },
    {
      name: "preserves a conditional fallback returning undefined",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default(() => enabled ? [] : undefined);',
    },
    {
      name: "preserves an absent fallback argument",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default();',
    },
    {
      name: "accepts the documented array default",
      filename: PRODUCTION,
      code: DOCUMENTED_ARRAY_DEFAULT,
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
      name: "allows an array default without optional (own filename: same code as the documented example)",
      filename: "src/schema-default.ts",
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
      code: "const z = toolkit; const Items = z.array(z.string()).optional().default([]);",
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
      code: DOCUMENTED_OPTIONAL_ARRAY_DEFAULT,
    },
    {
      name: "ignores generated files",
      filename: "src/generated/schema.ts",
      code: DOCUMENTED_OPTIONAL_ARRAY_DEFAULT,
    },
  ],
  invalid: [
    {
      name: "fixes an exclusively owned aliased legacy namespace",
      filename: PRODUCTION,
      code: "import * as schema from 'zod/v3'; const Items = schema.array(schema.string()).optional().default([]);",
      output:
        "import * as schema from 'zod/v3'; const Items = schema.array(schema.string()).default([]);",
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "preserves a public legacy schema's wrapper introspection",
      filename: PRODUCTION,
      code: "import { z } from 'zod/v3'; export const Items = z.array(z.string()).optional().default([]);",
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "preserves a legacy factory prototype observer",
      filename: PRODUCTION,
      code: "import { z } from 'zod/v3'; z.array(z.string()).constructor.prototype.optional = observe; const Items = z.array(z.string()).optional().default([]);",
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "preserves legacy runtime observations after the declaration",
      filename: PRODUCTION,
      code: "import { z } from 'zod/v3'; const Items = z.array(z.string()).optional().default([]); observe();",
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "preserves legacy schema type references",
      filename: PRODUCTION,
      code: "import { z } from 'zod/v3'; const Items = z.array(z.string()).optional().default([]); type Item = typeof Items;",
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },

    {
      name: "preserves Zod 3 semantics with a literal array fallback",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default([]);',
      output:
        'import { z } from "zod/v3"; const Items = z.array(z.string()).default([]);',
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "supports a function returning a literal array",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default(function () { return []; });',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "supports an arrow block returning a literal array",
      filename: PRODUCTION,
      code: 'import { z } from "zod/v3"; const Items = z.array(z.string()).optional().default(() => { return []; });',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "reports the documented Zod 4 chain without suppressing constructor hooks",
      filename: PRODUCTION,
      code: DOCUMENTED_OPTIONAL_ARRAY_DEFAULT,
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "supports array method syntax",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.string().array().optional().default([]);',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "supports lazy array defaults",
      filename: PRODUCTION,
      code: 'import { z } from "zod"; const Items = z.array(z.string()).optional().default(() => []);',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "resolves an aliased namespace import",
      filename: PRODUCTION,
      code: 'import { z as schema } from "zod/v4"; const Items = schema.array(schema.string()).optional().default([]);',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "resolves an aliased named array constructor",
      filename: PRODUCTION,
      code: 'import { array as list, string } from "zod"; const Items = list(string()).optional().default([]);',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
    {
      name: "finds the pair below an outer metadata method",
      filename: PRODUCTION,
      code: 'import * as schema from "zod"; const Items = schema.array(schema.string()).optional().default([]).describe("items");',
      output: null,
      errors: [{ messageId: "redundantOptionalArrayDefault" }],
    },
  ],
});
