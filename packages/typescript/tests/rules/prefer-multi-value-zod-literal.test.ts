// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";
import { z } from "zod";

import rule, {
  PREFER_MULTI_VALUE_ZOD_LITERAL_DOCUMENTATION,
} from "../../src/rules/prefer-multi-value-zod-literal.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

it("does not automatically change the public schema and validation error contracts", () => {
  const original = z.union([z.literal(1), z.literal(2)]);
  const replacement = z.literal([1, 2]);
  expect(original.options).toHaveLength(2);
  expect("options" in replacement).toBe(false);
  expect(original.safeParse(3).error?.issues[0]?.code).toBe("invalid_union");
  expect(replacement.safeParse(3).error?.issues[0]?.code).toBe("invalid_value");
  expect(rule.meta.fixable).toBeUndefined();
});

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
        null,
      errors: [ERROR],
    },
    {
      name: "reports without rewriting the motivating numeric domain",
      code: "import { z } from 'zod/v4'; export const AllowedConcurrencySchema = z.union([z.literal(2), z.literal(8), z.literal(16), z.literal(32), z.literal(128), z.literal(256)]);",
      output:
        null,
      errors: [ERROR],
    },
    {
      name: "reports without rewriting a two-arm numeric union",
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(1), z.literal(2)]);",
      output:
        null,
      errors: [ERROR],
    },
    {
      name: "reports without rewriting every supported primitive syntax",
      code: "import { z } from 'zod/v4'; export const V = z.union([z.literal(-1), z.literal(2n), z.literal(true), z.literal(null), z.literal(undefined), z.literal(`x`)]);",
      output:
        null,
      errors: [ERROR],
    },
    {
      name: "supports an explicit version for bare Zod imports",
      code: "import { z } from 'zod'; export const V = z.union([z.literal(1), z.literal(2)]);",
      output: null,
      options: [{ zodMajorVersion: 4 }],
      errors: [ERROR],
    },
    {
      name: "recognizes the explicit Zod 4 mini entrypoint",
      code: "import * as schema from 'zod/v4-mini'; export const V = schema.union([schema.literal(false), schema.literal(true)]);",
      output:
        null,
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


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "literal-union-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/schema.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/schema.ts",
        "source": "import { z } from 'zod/v4'; export const Version = z[\"union\"]([z[\"literal\"](1), z[\"literal\"](2), z[\"literal\"](3)]);"
      }
    ]
  },
  {
    "id": "literal-union-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/schema.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/schema.ts",
        "source": "import { z } from 'zod/v4'; export const Version = z[auditDynamicMember]([z[auditDynamicMember](1), z[auditDynamicMember](2), z[auditDynamicMember](3)]);"
      }
    ]
  }
] } });
});
