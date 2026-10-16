// vitest: shared-module-graph
import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";
import { Linter } from "eslint";
import zodPlugin from "eslint-plugin-zod";
import { z } from "zod";

import rule, {
  NO_IMPOSSIBLE_ZOD_LITERAL_BOUNDS_DOCUMENTATION,
} from "../../src/rules/no-impossible-zod-literal-bounds.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parser: tsParser },
});
const PRODUCTION = "src/schema.ts";
const withZod = (code: string): string => `import { z } from "zod"; ${code}`;

RULE_TESTER.run("modern Zod integer and length domains", rule, {
  valid: [
    { name: "keeps compatible erased numeric bounds", code: withZod('const S = z.number().min((3 as const)).max((3 as const));'), filename: PRODUCTION },
    { name: "keeps a dynamic bound opaque through a cast", code: withZod('const S = z.number().min((lower as number)).max((0 as const));'), filename: PRODUCTION },
    { name: "keeps transforms excluded with erased literal bounds", code: withZod('const S = z.number().min((5 as const)).max((4 as const)).transform(String);'), filename: PRODUCTION },

    { code: withZod("const S = z.int().gt(0).lte(1);"), filename: PRODUCTION },
    {
      code: withZod("const S = z.int32().gte(2147483647);"),
      filename: PRODUCTION,
    },
    { code: withZod("const S = z.uint32().lte(0);"), filename: PRODUCTION },
    {
      code: withZod("const S = z.string().min(.2).max(1.2);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.array(z.string()).min(.2).max(1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.int().min(lower).max(1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.int().gt(0).lt(1).transform(String);"),
      filename: PRODUCTION,
    },
    {
      code: withZod(
        "const S = (z.string().min(.2).max(.8) as z.ZodString).default('sentinel');",
      ),
      filename: PRODUCTION,
    },
    {
      code: withZod(
        "const S = (z.string().min(.2).max(.8) satisfies z.ZodString).default('sentinel');",
      ),
      filename: PRODUCTION,
    },
    {
      code: withZod(
        "const S = (z.int().gt(0).lt(1) as z.ZodNumber).optional();",
      ),
      filename: PRODUCTION,
    },
    {
      code: withZod(
        "const S = (z.int().gt(0).lt(1) satisfies z.ZodNumber).optional();",
      ),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = (z.int().gt(0).lt(1))!.nullable();"),
      filename: PRODUCTION,
    },
    {
      code: withZod(
        "const S = ((z.int().gt(0).lt(1) as z.ZodNumber) satisfies z.ZodNumber)!.optional();",
      ),
      filename: PRODUCTION,
    },
    {
      code: "import { z } from 'zod'; function build(z: SchemaKit) { return z.int().gt(0).lt(1); }",
      filename: PRODUCTION,
    },
  ],
  invalid: [
    { name: "retains contradictory literal bounds through const assertions", code: withZod('const S = z.number().min((5 as const)).max((4 as const));'), filename: PRODUCTION, errors: [{ messageId: "impossibleBounds" }] },
    { name: "retains numeric bounds through satisfies", code: withZod('const S = z.number().min((5 satisfies number)).max((4 satisfies number));'), filename: PRODUCTION, errors: [{ messageId: "impossibleBounds" }] },
    { name: "retains an erased literal inside a unary bound", code: withZod('const S = z.number().min(-(4 as const)).max((-5 as const));'), filename: PRODUCTION, errors: [{ messageId: "impossibleBounds" }] },

    {
      code: withZod("const S = z.int().gt(0).lt(1);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = (z.int().gt(0).lt(1) as z.ZodNumber);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = (z.int().gt(0).lt(1) as z.ZodNumber).lte(2);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: "import { int as integer } from 'zod/v4'; const S=integer().gt(0).lt(1);",
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.int32().gte(2147483648);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.uint32().max(-1);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().min(.2).max(.8);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.array(z.string()).length(.5);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
  ],
});

RULE_TESTER.run("no-impossible-zod-literal-bounds", rule, {
  valid: [
    {
      code: NO_IMPOSSIBLE_ZOD_LITERAL_BOUNDS_DOCUMENTATION.examples[0].files[0]
        .source,
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().min(3).max(3);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().gt(3).lt(4);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().int().gte(0).lt(1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().int().min(5).max(4);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().int().gt(-2).lte(-1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().int().min(0.1).max(1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().int().min(lower).max(1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod(
        "const S = z.number().int().gt(9007199254740990).lt(9007199254740992);",
      ),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().gte(-2).lt(+2);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().positive().max(1);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.number().nonnegative().max(0);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.string().min(3).max(3);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.string().min(2).length(3).max(4);"),
      filename: PRODUCTION,
    },
    {
      code: withZod("const S = z.array(z.string()).length(2).length(2);"),
      filename: PRODUCTION,
    },
    {
      name: "does not confuse compatible Zod string formats with bounds",
      code: withZod("const S = z.string().uuid().guid();"),
      filename: PRODUCTION,
    },
    {
      name: "skips a chain containing a non-bound validator",
      code: withZod("const S = z.string().uuid().min(5).max(4);"),
      filename: PRODUCTION,
    },
    {
      name: "skips dynamic numeric bounds",
      code: withZod("const S = z.number().min(lower).max(0);"),
      filename: PRODUCTION,
    },
    {
      name: "skips dynamic length bounds",
      code: withZod("const S = z.string().min(5).max(limit);"),
      filename: PRODUCTION,
    },
    {
      name: "skips transforms even when their input constraints conflict",
      code: withZod("const S = z.string().min(5).max(4).transform(String);"),
      filename: PRODUCTION,
    },
    {
      name: "skips schemas passed to pipe",
      code: withZod("const S = z.string().pipe(z.string().min(5).max(4));"),
      filename: PRODUCTION,
    },
    {
      name: "skips schemas passed to preprocess",
      code: withZod(
        "const S = z.preprocess(String, z.string().min(5).max(4));",
      ),
      filename: PRODUCTION,
    },
    {
      name: "skips schemas passed to an aliased preprocess import",
      code: 'import { z, preprocess as prepare } from "zod"; const S = prepare(String, z.string().min(5).max(4));',
      filename: PRODUCTION,
    },
    {
      name: "does not mistake a shadowed z binding for the import",
      code: 'import { z } from "zod"; function build(z: SchemaKit) { return z.number().min(5).max(4); }',
      filename: PRODUCTION,
    },
    {
      name: "ignores same-shaped local APIs",
      code: "const S = z.number().min(5).max(4);",
      filename: PRODUCTION,
    },
    {
      name: "ignores same-shaped non-Zod imports",
      code: 'import { z } from "./schema-kit"; const S = z.number().min(5).max(4);',
      filename: PRODUCTION,
    },
    {
      name: "ignores test files",
      code: NO_IMPOSSIBLE_ZOD_LITERAL_BOUNDS_DOCUMENTATION.examples[1].files[0]
        .source,
      filename: "src/schema.test.ts",
    },
    {
      name: "ignores generated files",
      code: withZod("const S = z.number().min(5).max(4);"),
      filename: "src/generated/schema.ts",
    },
  ],
  invalid: [
    {
      name: "integer interval excludes both adjacent integers",
      code: withZod("const S = z.number().int().gt(0).lt(1);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "fractional closed interval contains no integer",
      code: withZod("const S = z.number().int().min(0.1).max(0.9);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "negative integer interval contains no integer",
      code: withZod("const S = z.number().gt(-2).lt(-1).int();"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "reports positive constrained to at most zero",
      code: withZod("const S = z.number().positive().max(0);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "reports negative constrained to at least zero",
      code: withZod("const S = z.number().negative().min(0);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().min(5).max(4);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().max(4).min(5);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().gt(3).lt(3);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().gte(3).lt(3);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().gt(3).lte(3);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().min(5).max(4);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().length(3).min(4);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().max(2).length(3);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.array(z.string()).length(2).length(3);"),
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "resolves an aliased z import",
      code: 'import { z as schema } from "zod/v4"; const S = schema.string().min(5).max(4);',
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "resolves a namespace import",
      code: 'import * as schema from "zod"; const S = schema.number().gt(0).max(0);',
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "resolves an aliased named constructor",
      code: 'import { string as zString } from "zod"; const S = zString().min(5).max(4);',
      filename: PRODUCTION,
      errors: [{ messageId: "impossibleBounds" }],
    },
  ],
});

it("assigns integer gaps and real contradictions to different owners", () => {
  const linter = new Linter();
  const config = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { zod: zodPlugin, sarj: { rules: { bounds: rule } } },
      rules: { "zod/no-conflicting-checks": "error", "sarj/bounds": "error" },
    },
  ] as const;
  const gap = linter.verify(
    withZod("const S = z.number().int().gt(0).lt(1);"),
    config,
    PRODUCTION,
  );
  const contradiction = linter.verify(
    withZod("const S = z.number().int().min(5).max(4);"),
    config,
    PRODUCTION,
  );
  expect(gap.map(({ ruleId }) => ruleId)).toEqual(["sarj/bounds"]);
  expect(contradiction.map(({ ruleId }) => ruleId)).toEqual([
    "zod/no-conflicting-checks",
  ]);
});

it("keeps upstream contradictions and new native-domain gaps under one owner", () => {
  const config = [
    {
      files: ["**/*.ts"],
      languageOptions: { parser: tsParser },
      plugins: { zod: zodPlugin, sarj: { rules: { bounds: rule } } },
      rules: {
        "zod/no-conflicting-checks": "error",
        "sarj/bounds": ["error", { delegateRealContradictions: true }],
      },
    },
  ] as const;
  for (const expression of [
    "z.number().min(5).max(4)",
    "z.string().min(5).max(4)",
    "z.int().min(5).max(4)",
  ]) {
    const findings = new Linter().verify(
      withZod(`const S=${expression};`),
      config,
      PRODUCTION,
    );
    expect(findings.map(({ ruleId }) => ruleId)).toEqual([
      "zod/no-conflicting-checks",
    ]);
  }
  for (const expression of [
    "z.int().gt(0).lt(1)",
    "z.int32().min(2147483648)",
    "z.uint32().max(-1)",
    "z.string().min(.2).max(.8)",
  ]) {
    const findings = new Linter().verify(
      withZod(`const S=${expression};`),
      config,
      PRODUCTION,
    );
    expect(findings.map(({ ruleId }) => ruleId)).toEqual(["sarj/bounds"]);
  }
});

it("matches native Zod integer formats and length domains", () => {
  expect(z.int().gt(0).lt(1).safeParse(0.5).success).toBe(false);
  expect(z.int().gt(0).lte(1).safeParse(1).success).toBe(true);
  expect(z.int32().gte(2147483648).safeParse(2147483648).success).toBe(false);
  expect(z.int32().gte(2147483647).safeParse(2147483647).success).toBe(true);
  expect(z.uint32().max(-1).safeParse(-1).success).toBe(false);
  expect(z.uint32().max(0).safeParse(0).success).toBe(true);
  expect(z.string().min(0.2).max(0.8).safeParse("").success).toBe(false);
  expect(z.string().min(0.2).max(0.8).safeParse("a").success).toBe(false);
  expect(z.array(z.string()).length(0.5).safeParse([]).success).toBe(false);
  expect(z.array(z.string()).min(0.2).max(1).safeParse(["a"]).success).toBe(
    true,
  );
  expect(
    z.string().min(0.2).max(0.8).default("sentinel").safeParse(undefined)
      .success,
  ).toBe(true);
  expect(z.int().gt(0).lt(1).optional().safeParse(undefined).success).toBe(
    true,
  );
  expect(z.int().gt(0).lt(1).nullable().safeParse(null).success).toBe(true);
});
