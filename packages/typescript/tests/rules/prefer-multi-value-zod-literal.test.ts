import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION,
} from "../../src/rules/prefer-multi-value-zod-literal.js";

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
const ERROR = { messageId: "useMultiValueLiteral" as const };

RULE_TESTER.run("prefer-multi-value-zod-literal", rule, {
  valid: [
    {
      name: "public no-match example",
      filename:
        PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION.examples[0].focusPath,
      code: PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION.examples[0].files[0]
        .source,
    },
    "import { z } from 'zod'; export const V = z.union([z.literal(1), z.string()]);",
    "import { z } from 'zod/v4'; export const V = z.union([z.literal('a'), z.literal('b')]);",
    "import { z } from 'zod/v4'; export const V = z.union([z.literal(/a/), z.literal(/b/)]);",
    "import { z } from 'zod/v4'; export const V = z.union([z.literal(value), z.literal(2)]);",
    "import { z } from 'zod/v4'; export const V = z.union([z.literal(`a${value}`), z.literal('b')]);",
    "import { z } from 'zod/v4'; export const V = z.union([z.literal(1).describe('one'), z.literal(2)]);",
    "import { z } from 'zod/v4'; export const V = z.union([z.literal(1), ...schemas]);",
    "import { z } from './builder.js'; export const V = z.union([z.literal(1), z.literal(2)]);",
    {
      name: "ignores bare Zod imports unless version 4 is configured",
      code: "import { z } from 'zod'; export const V = z.union([z.literal(1), z.literal(2)]);",
    },
    {
      name: "ignores a shadowed Zod import",
      code: "import { z } from 'zod/v4'; function schema(z: Builder) { return z.union([z.literal(1), z.literal(2)]); }",
    },
    {
      name: "ignores test fixtures",
      filename: "src/schema.test.ts",
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(1), z.literal(2)]);",
    },
    {
      name: "ignores generated files",
      filename: "src/schema.ts",
      code: "// @generated\nimport { z } from 'zod/v4'; export const V = z.union([z.literal(1), z.literal(2)]);",
    },
  ],
  invalid: [
    {
      name: "public match example",
      filename:
        PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION.examples[1].focusPath,
      code: PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION.examples[1].files[0]
        .source.replace("from 'zod'", "from 'zod/v4'"),
      output:
        "import { z } from 'zod/v4'; export const Version = z.literal([1, 2, 3]);",
      errors: [ERROR],
    },
    {
      name: "fixes the motivating numeric domain",
      code: "import { z } from 'zod/v4'; export const AllowedConcurrencySchema = z.union([z.literal(2), z.literal(8), z.literal(16), z.literal(32), z.literal(128), z.literal(256)]);",
      output:
        "import { z } from 'zod/v4'; export const AllowedConcurrencySchema = z.literal([2, 8, 16, 32, 128, 256]);",
      errors: [ERROR],
    },
    {
      name: "fixes a two-arm numeric union",
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(1), z.literal(2)]);",
      output:
        "import { z } from 'zod/v4'; export const V = z.literal([1, 2]);",
      errors: [ERROR],
    },
    {
      name: "fixes every supported primitive syntax",
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(-1), z.literal(2n), z.literal(true), z.literal(null), z.literal(undefined), z.literal(`x`)]);",
      output:
        "import { z } from 'zod/v4'; export const V = z.literal([-1, 2n, true, null, undefined, `x`]);",
      errors: [ERROR],
    },
    {
      name: "supports an explicit version for bare Zod imports",
      code: "import { z } from 'zod'; export const V = z.union([z.literal(1), z.literal(2)]);",
      output: "import { z } from 'zod'; export const V = z.literal([1, 2]);",
      options: [{ zodMajorVersion: 4 }],
      errors: [ERROR],
    },
    {
      name: "recognizes the explicit Zod 4 mini entrypoint",
      code: "import * as schema from 'zod/v4-mini'; export const V = schema.union([schema.literal(false), schema.literal(true)]);",
      output:
        "import * as schema from 'zod/v4-mini'; export const V = schema.literal([false, true]);",
      errors: [ERROR],
    },
    {
      name: "reports without fixing when comments would be lost",
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(1), /* reserved */ z.literal(2)]);",
      output: null,
      errors: [ERROR],
    },
  ],
});
