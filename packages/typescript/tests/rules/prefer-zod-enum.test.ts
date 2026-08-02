import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/prefer-zod-enum.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});

ruleTester.run("prefer-zod-enum", rule, {
  valid: [
    'import { z } from "zod"; const S = z.enum(["a", "b"]);',
    'import { z } from "zod"; const S = z.union([z.string(), z.number()]);',
    'import { z } from "zod"; const S = z.union([z.literal("a"), other]);',
    'import { z } from "zod"; const S = z.union([]);',
    'import { z } from "zod"; const S = z.union([other, ...schemas]);',
    'import { z } from "zod"; const S = z["union"]([z.literal("a")]);',
    'import { z } from "zod"; const S = z.union([z.literal("a"), local.literal("b")]);',
    'const z = localSchemaBuilder; const S = z.union([z.literal("a")]);',
  ],
  invalid: [
    {
      code: 'import { z } from "zod"; const S = z.union([z.literal("word"), z.literal("phrase")]);',
      output: 'import { z } from "zod"; const S = z.enum(["word", "phrase"]);',
      errors: [{ messageId: "preferEnum" }],
    },
    {
      code: "import * as zod from 'zod'; const S = zod.union([zod.literal('a'), zod.literal('b')]);",
      output: "import * as zod from 'zod'; const S = zod.enum(['a', 'b']);",
      errors: [{ messageId: "preferEnum" }],
    },
    {
      code: 'import { z } from "zod"; const S = z.union([z.literal("a"), /* keep */ z.literal("b")]);',
      output: null,
      errors: [{ messageId: "preferEnum" }],
    },
    {
      code: 'import { z } from "zod"; const S = z.union([z.literal("a"), ...schemas]);',
      output: null,
      errors: [{ messageId: "preferEnum" }],
    },
    {
      code: 'import { z } from "zod"; const S = z.union([z.literal("a"), z.literal(value)]);',
      output: null,
      errors: [{ messageId: "preferEnum" }],
    },
    {
      code: 'import { z } from "zod"; const S = z.union([z.literal("a"), z.literal(1)]);',
      output: null,
      errors: [{ messageId: "preferEnum" }],
    },
    {
      code: 'import { z as schema } from "zod"; const S = schema.union([schema.literal("a"), schema.literal("b")]);',
      output: 'import { z as schema } from "zod"; const S = schema.enum(["a", "b"]);',
      errors: [{ messageId: "preferEnum" }],
    },
  ],
});
