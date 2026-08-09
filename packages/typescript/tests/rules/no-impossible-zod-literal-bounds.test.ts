import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  noImpossibleZodLiteralBoundsDocumentation,
} from "../../src/rules/no-impossible-zod-literal-bounds.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: { parser: tsParser },
});
const production = "src/schema.ts";
const withZod = (code: string): string => `import { z } from "zod"; ${code}`;

ruleTester.run("no-impossible-zod-literal-bounds", rule, {
  valid: [
    {
      code: noImpossibleZodLiteralBoundsDocumentation.examples[0].files[0].source,
      filename: production,
    },
    { code: withZod("const S = z.number().min(3).max(3);"), filename: production },
    { code: withZod("const S = z.number().gt(3).lt(4);"), filename: production },
    { code: withZod("const S = z.number().gte(-2).lt(+2);"), filename: production },
    { code: withZod("const S = z.string().min(3).max(3);"), filename: production },
    { code: withZod("const S = z.string().min(2).length(3).max(4);"), filename: production },
    { code: withZod("const S = z.array(z.string()).length(2).length(2);"), filename: production },
    {
      name: "does not confuse compatible Zod string formats with bounds",
      code: withZod("const S = z.string().uuid().guid();"),
      filename: production,
    },
    {
      name: "skips a chain containing a non-bound validator",
      code: withZod("const S = z.string().uuid().min(5).max(4);"),
      filename: production,
    },
    {
      name: "skips dynamic numeric bounds",
      code: withZod("const S = z.number().min(lower).max(0);"),
      filename: production,
    },
    {
      name: "skips dynamic length bounds",
      code: withZod("const S = z.string().min(5).max(limit);"),
      filename: production,
    },
    {
      name: "skips transforms even when their input constraints conflict",
      code: withZod("const S = z.string().min(5).max(4).transform(String);"),
      filename: production,
    },
    {
      name: "skips schemas passed to pipe",
      code: withZod("const S = z.string().pipe(z.string().min(5).max(4));"),
      filename: production,
    },
    {
      name: "skips schemas passed to preprocess",
      code: withZod("const S = z.preprocess(String, z.string().min(5).max(4));"),
      filename: production,
    },
    {
      name: "skips schemas passed to an aliased preprocess import",
      code: 'import { z, preprocess as prepare } from "zod"; const S = prepare(String, z.string().min(5).max(4));',
      filename: production,
    },
    {
      name: "does not mistake a shadowed z binding for the import",
      code: 'import { z } from "zod"; function build(z: SchemaKit) { return z.number().min(5).max(4); }',
      filename: production,
    },
    {
      name: "ignores same-shaped local APIs",
      code: "const S = z.number().min(5).max(4);",
      filename: production,
    },
    {
      name: "ignores same-shaped non-Zod imports",
      code: 'import { z } from "./schema-kit"; const S = z.number().min(5).max(4);',
      filename: production,
    },
    {
      name: "ignores test files",
      code: noImpossibleZodLiteralBoundsDocumentation.examples[1].files[0].source,
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
      code: withZod("const S = z.number().min(5).max(4);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().max(4).min(5);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().gt(3).lt(3);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().gte(3).lt(3);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.number().gt(3).lte(3);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().min(5).max(4);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().length(3).min(4);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.string().max(2).length(3);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      code: withZod("const S = z.array(z.string()).length(2).length(3);"),
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "resolves an aliased z import",
      code: 'import { z as schema } from "zod/v4"; const S = schema.string().min(5).max(4);',
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "resolves a namespace import",
      code: 'import * as schema from "zod"; const S = schema.number().gt(0).max(0);',
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
    {
      name: "resolves an aliased named constructor",
      code: 'import { string as zString } from "zod"; const S = zString().min(5).max(4);',
      filename: production,
      errors: [{ messageId: "impossibleBounds" }],
    },
  ],
});
