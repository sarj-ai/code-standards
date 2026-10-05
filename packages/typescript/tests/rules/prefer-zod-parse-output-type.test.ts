import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";

import rule, {
  PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION,
} from "../../src/rules/prefer-zod-parse-output-type.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const IMPORT = 'import { z } from "zod";\n';
const SCHEMA = "const WireSchema = z.object({ id: z.string() });";
const CONTRACT = "interface ParsedRow { id: string }";
const errors = [{ messageId: "handWrittenParsedOutput" }];

TESTER.run("prefer-zod-parse-output-type", rule, {
  valid: [
    `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}) as ParsedRow; }`,
    PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.examples[0].files[0].source,
    `${IMPORT} interface Row { id: string } const RowSchema = z.object({ id: z.string() }); function get(): Row { return RowSchema.parse({}); }`,
    `${IMPORT} import type { ParsedRow } from './contracts.js'; ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} interface ParsedRow { id: string; optional?: string } ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} interface ParsedRow { readonly id: string } ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} interface ParsedRow { status: string } const WireSchema = z.object({ status: z.literal('ok') }); function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} ${CONTRACT} const WireSchema: z.ZodType<ParsedRow> = z.object({ id: z.string() }); function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} ${CONTRACT} const WireSchema = z.object({ id: z.string() }).transform((row) => row); function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { const parsed = WireSchema.parse({}); const alias = parsed; return alias; }`,
    `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { let parsed = WireSchema.parse({}); return parsed; }`,
    `${IMPORT} ${CONTRACT} ${SCHEMA} function get(other: ParsedRow, choose: boolean): ParsedRow { if (choose) return WireSchema.parse({}); return other; }`,
    `${IMPORT} ${CONTRACT} ${SCHEMA} function get(WireSchema: { parse(value: unknown): ParsedRow }): ParsedRow { return WireSchema.parse({}); }`,
    `import { z } from './zod-helper.js'; ${CONTRACT} ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${CONTRACT} const parser = { parse(): ParsedRow { return { id: 'x' }; } }; function get(): ParsedRow { return parser.parse(); }`,
    `${IMPORT} interface ParsedRow { child: { id: string } } const WireSchema = z.object({ child: z.object({ id: z.string() }) }); function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} interface ParsedRow { id: string } interface ParsedRow { other?: string } ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
    `${IMPORT} ${CONTRACT} ${SCHEMA} const OtherSchema = z.object({ id: z.string() }); function first(): ParsedRow { return WireSchema.parse({}); } function second(): ParsedRow { return OtherSchema.parse({}); }`,
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
      filename: "src/generated/api.ts",
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
      filename: "src/example.test.ts",
    },
  ],
  invalid: [
    {
      code: PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.examples[1].files[0]
        .source,
      errors,
      output: null,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
      errors,
      output: null,
    },
    {
      code: `${IMPORT} type ParsedRow = { id: string }; ${SCHEMA} function get(): ParsedRow { return WireSchema.parse({}); }`,
      errors,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} async function get(): Promise<ParsedRow | null> { return choose ? WireSchema.parse({}) : null; }`,
      errors,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} const get = (): ParsedRow => WireSchema.parse({});`,
      errors,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow { const parsed = WireSchema.parse({}); observe(parsed.id); return parsed; }`,
      errors,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow | null { const parsed = WireSchema.safeParse({}); if (!parsed.success) return null; return parsed.data; }`,
      errors,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function get(): ParsedRow | undefined { const parsed = WireSchema.safeParse({}); return parsed.success ? parsed.data : undefined; }`,
      errors,
    },
    {
      code: `${IMPORT} ${CONTRACT} ${SCHEMA} function first(): ParsedRow { return WireSchema.parse({}); } function second(): ParsedRow { return WireSchema.parse({}); }`,
      errors,
    },
    {
      code: `import { z as schema } from 'zod/v4'; ${CONTRACT} const WireSchema = schema.object({ id: schema.string() }); function get(): ParsedRow { return WireSchema.parse({}); }`,
      errors,
    },
    {
      code: `${IMPORT} interface ParsedRow { id: string | null; label?: string } const WireSchema = z.object({ id: z.string().nullable(), label: z.string().optional() }); function get(): ParsedRow { return WireSchema.parse({}); }`,
      errors,
    },
  ],
});
