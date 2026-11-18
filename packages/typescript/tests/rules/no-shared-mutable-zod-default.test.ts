// vitest: shared-module-graph
import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/no-shared-mutable-zod-default.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("no-shared-mutable-zod-default", rule, {
  valid: [
  "import { z } from 'zod/v4'; const shared = []; function defaults() { return shared; } z.array(z.string()).default(defaults);",
  "import { z } from 'zod/v4'; const shared = []; function defaults() { return shared; } Object.freeze(defaults()); z.array(z.string()).default(defaults);",
  "import { z } from 'zod/v4'; const shared = []; const defaults = () => shared; expose(defaults); z.array(z.string()).default(defaults);",
  "import { z } from 'zod/v4'; const shared = []; eval('Object.freeze(shared)'); z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; const run = Function('return 1'); z.array(z.string()).default(() => shared);",

  "import { z } from 'zod/v4'; z.array(z.string()).default(() => []);",
  "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).default(shared);",
  "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).default(() => [...shared]);",
  "import { z } from 'zod/v4'; const shared = 'ready'; z.string().default(() => shared);",
  "import { z } from './custom.js'; const shared = []; z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; function run(z) { z.array(z.string()).default(() => shared); }",
  "import { z } from 'zod/v4'; const shared = Object.freeze({}); z.object({}).default(() => shared);",
  "import { z } from 'zod/v4'; let shared = []; z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; z.array = custom; z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; z.array(z.string()).default(() => { const local = []; return local; });",
  "import { z } from 'zod/v4'; const shared = [Object.freeze({})]; Object.freeze(shared); z.any().default(() => shared);",
  "import { z } from 'zod/v4'; const shared = [Object.freeze({})]; z.any().default(() => shared).readonly();",
  "import { z } from 'zod/v4'; const shared = [{ items: [] }]; Object.freeze(shared[0]); Object.freeze(shared); z.any().default(() => shared);",
  "import { z } from 'zod/v3'; const shared = []; z.array(z.string()).default(() => shared);",
  "import { z } from 'zod'; const shared = []; z.array(z.string()).default(() => shared);",
  {
    "code": "import { z } from 'zod/v3'; const shared = []; z.array(z.string()).default(() => shared);",
    "options": [
      {
        "zodMajorVersion": 4
      }
    ]
  },
  "import { z } from 'zod/v4'; const shared = []; Object.freeze(shared); z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; const alias = shared; Object.freeze(alias); z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).default(() => shared).readonly();",
  "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).default(() => shared).transform(value => value.slice());",
  "import { z } from 'zod/v4'; const shared = []; const Schema = z.array(z.string()); Object.defineProperty(Schema, 'default', { value: () => 'safe' }); Schema.default(() => shared);",
  "import { z } from 'zod/v4'; const shared = new Map(); Map = CustomMap; z.map(z.string(), z.number()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = new Set(); globalThis.Set = CustomSet; z.set(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; Object.freeze(shared); Object.keys(other); z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; opaqueFreeze(shared); z.array(z.string()).default(() => shared);",
  "import { z } from 'zod/v4'; const shared = []; shared.push({ items: [] }); z.array(z.any()).default(() => shared).readonly();",
  "import { z } from 'zod/v4'; const shared = {}; shared.items = []; Object.freeze(shared); z.any().default(() => shared);"
],
  invalid: [
  {
    "code": "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = {}; z.object({}).default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = new Map(); z.map(z.string(), z.number()).default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = []; const Schema = z.array(z.string()); const alias = shared; Schema.default(() => alias);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { array as list, string } from 'zod/v4'; const shared = []; list(string()).default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod'; const shared = []; z.array(z.string()).default(() => shared);",
    "options": [
      {
        "zodMajorVersion": 4
      }
    ],
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = []; const Schema = z.array(z.string()); type Output = z.infer<typeof Schema>; Schema.default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = [{ values: [] }]; z.array(z.object({ values: z.array(z.string()) })).default(() => shared).readonly();",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = [{ values: [] }]; Object.freeze(shared); z.array(z.object({ values: z.array(z.string()) })).default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = new Map(); Object.freeze(shared); z.map(z.string(), z.number()).default(() => shared).readonly();",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  },
  {
    "code": "import { z } from 'zod/v4'; const shared = []; z.array(z.string()).transform(value => value.slice()).default(() => shared);",
    "errors": [
      {
        "messageId": "noSharedMutableZodDefault"
      }
    ]
  }
],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["no-shared-mutable-zod-default"])).resolves.toBeGreaterThan(0);
});
