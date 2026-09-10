import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { ESLint } from "eslint";
import { afterAll, describe, expect, it } from "vitest";

import plugin from "../../src/index.js";
import rule, {
  PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION,
} from "../../src/rules/prefer-zod-parse-output-type.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TYPED_RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: {
        allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"],
        maximumDefaultProjectFileMatchCount_THIS_WILL_SLOW_DOWN_LINTING: 30,
      },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

const IMPORT = 'import { z } from "zod";\n';

new RuleTester({ languageOptions: { parser: tsParser } }).run(
  "prefer-zod-parse-output-type without type information",
  rule,
  {
    valid: [PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.examples[1].files[0].source],
    invalid: [],
  },
);

TYPED_RULE_TESTER.run("prefer-zod-parse-output-type", rule, {
  valid: [
    {
      name: "accepts the documented schema-derived return",
      filename: "zod-parse-output-derived.ts",
      code: PREFER_ZOD_PARSE_OUTPUT_TYPE_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "allows a domain contract with an additional optional property",
      filename: "zod-parse-output-optional-domain.ts",
      code: `${IMPORT}
        import type { OptionalDomainRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): OptionalDomainRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "leaves same-module twins to prefer-zod-infer",
      filename: "zod-parse-output-same-module.ts",
      code: `${IMPORT}
        interface Row { id: string }
        const RowSchema = z.object({ id: z.string() });
        function get(): Row { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a wider property type with the same property keys",
      filename: "zod-parse-output-wider-property.ts",
      code: `${IMPORT}
        interface DomainRecord { status: string }
        const RowSchema = z.object({ status: z.literal("ok") });
        function get(): DomainRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a schema intentionally constrained by the contract",
      filename: "zod-parse-output-constrained.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema: z.ZodType<TrialChannelRecord> = z.object({
          applicationId: z.string(), channelId: z.string().nullable(),
        });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a readonly domain contract",
      filename: "zod-parse-output-readonly.ts",
      code: `${IMPORT}
        import type { ReadonlyRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string() });
        function get(): ReadonlyRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "allows a generic domain contract",
      filename: "zod-parse-output-generic.ts",
      code: `${IMPORT}
        import type { GenericRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ data: z.string() });
        function get(): GenericRecord<string> { return RowSchema.parse({}); }`,
    },
    {
      name: "does not trust an unrelated parse method",
      filename: "zod-parse-output-unrelated-parser.ts",
      code: `import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const parser = { parse(): TrialChannelRecord { return { applicationId: "a", channelId: null }; } };
        function get(): TrialChannelRecord { return parser.parse(); }`,
    },
    {
      name: "does not infer an indirect data flow",
      filename: "zod-parse-output-indirect.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { const parsed = RowSchema.parse({}); return parsed; }`,
    },
    {
      name: "allows an augmented interface whose ownership is split",
      filename: "zod-parse-output-augmented.ts",
      code: `${IMPORT}
        import type { AugmentedRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): AugmentedRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "does not follow a schema composed from another local schema",
      filename: "zod-parse-output-composed.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const WireSchema = z.object({ application_id: z.string(), channel_id: z.string().nullable() });
        const RowSchema = WireSchema.transform((row) => ({
          applicationId: row.application_id, channelId: row.channel_id,
        }));
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "honors an exact rule suppression",
      filename: "zod-parse-output-suppressed.ts",
      code: `/* eslint-disable @rule-tester/prefer-zod-parse-output-type */
        ${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "does not report parsed return contracts in tests",
      filename: "zod-parse-output-return.test.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
    },
    {
      name: "skips a contract produced by multiple distinct schemas",
      filename: "zod-parse-output-ambiguous-owner.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const PrimarySchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        const LegacySchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function primary(): TrialChannelRecord { return PrimarySchema.parse({}); }
        function legacy(): TrialChannelRecord { return LegacySchema.parse({}); }`,
    },
  ],
  invalid: [
    {
      name: "reports the documented hand-written parsed return",
      filename: "zod-parse-output-documented.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports the cross-module nullable return that motivated the rule",
      filename: "zod-parse-output-trial-channel.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        declare const row: unknown;
        async function get(): Promise<null | TrialChannelRecord> {
          return row ? RowSchema.parse(row) : null;
        }`,
      errors: [
        {
          messageId: "handWrittenParsedOutput",
          data: { schemaName: "RowSchema", typeName: "TrialChannelRecord" },
        },
      ],
    },
    {
      name: "reports a renamed schema because return data flow proves the relationship",
      filename: "zod-parse-output-renamed.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const ValidatedDatabaseOutput = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): TrialChannelRecord { return ValidatedDatabaseOutput.parse({}); }`,
      errors: [
        {
          messageId: "handWrittenParsedOutput",
          data: { schemaName: "ValidatedDatabaseOutput", typeName: "TrialChannelRecord" },
        },
      ],
    },
    {
      name: "reports a renamed same-module schema without overlapping prefer-zod-infer",
      filename: "zod-parse-output-renamed-same-module.ts",
      code: `${IMPORT}
        interface PersistedRow { applicationId: string; channelId: string | null }
        const DatabaseResultSchema = z.object({
          applicationId: z.string(), channelId: z.string().nullable(),
        });
        function get(): PersistedRow { return DatabaseResultSchema.parse({}); }`,
      errors: [
        {
          messageId: "handWrittenParsedOutput",
          data: { schemaName: "DatabaseResultSchema", typeName: "PersistedRow" },
        },
      ],
    },
    {
      name: "reports a hand-written object type alias",
      filename: "zod-parse-output-alias.ts",
      code: `${IMPORT}
        import type { AliasRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function get(): AliasRecord { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "uses the type checker for nested objects and collections",
      filename: "zod-parse-output-nested.ts",
      code: `${IMPORT}
        import type { NestedRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({
          child: z.object({ value: z.string() }), tags: z.array(z.string()),
        });
        function get(): NestedRecord { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "emits one diagnostic when multiple returns repeat the same contract",
      filename: "zod-parse-output-deduplicated.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        function first(): TrialChannelRecord { return RowSchema.parse({}); }
        function second(): TrialChannelRecord { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports a synchronous concise arrow return",
      filename: "zod-parse-output-arrow.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        const get = (): TrialChannelRecord => RowSchema.parse({});`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports an asynchronous concise arrow return",
      filename: "zod-parse-output-async-arrow.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() });
        const get = async (): Promise<TrialChannelRecord> => RowSchema.parse({});`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
    {
      name: "reports a nullable schema output under the same nullish return envelope",
      filename: "zod-parse-output-nullable-schema.ts",
      code: `${IMPORT}
        import type { TrialChannelRecord } from "./zod-infer-cross-module-contracts.js";
        const RowSchema = z.object({ applicationId: z.string(), channelId: z.string().nullable() }).nullable();
        function get(): TrialChannelRecord | null { return RowSchema.parse({}); }`,
      errors: [{ messageId: "handWrittenParsedOutput" }],
    },
  ],
});

describe("prefer-zod-infer precedence", () => {
  const eslint = new ESLint({
    overrideConfigFile: true,
    overrideConfig: [
      {
        files: ["**/*.ts"],
        languageOptions: {
          parser: tsParser,
          parserOptions: {
            projectService: {
              allowDefaultProject: ["audit/*.ts"],
              maximumDefaultProjectFileMatchCount_THIS_WILL_SLOW_DOWN_LINTING: 3,
            },
            tsconfigRootDir: join(import.meta.dirname, "..", ".."),
          },
        },
        plugins: { "@sarj": plugin },
        rules: {
          "@sarj/prefer-zod-infer": "error",
          "@sarj/prefer-zod-parse-output-type": "warn",
        },
      },
    ],
  });

  it.each([
    {
      name: "canonical twins stay with the established rule",
      source: `${IMPORT}
        interface Row { id: string }
        const RowSchema = z.object({ id: z.string() });
        function get(): Row { return RowSchema.parse({}); }`,
      rules: ["@sarj/prefer-zod-infer"],
    },
    {
      name: "nested twins stay with the type-aware companion",
      source: `${IMPORT}
        interface Row { child: { id: string } }
        const RowSchema = z.object({ child: z.object({ id: z.string() }) });
        function get(): Row { return RowSchema.parse({}); }`,
      rules: ["@sarj/prefer-zod-parse-output-type"],
    },
    {
      name: "transformed twins stay with the type-aware companion",
      source: `${IMPORT}
        interface Row { id: string }
        const RowSchema = z.object({ id: z.string() }).transform((row) => row);
        function get(): Row { return RowSchema.parse({}); }`,
      rules: ["@sarj/prefer-zod-parse-output-type"],
    },
  ])("$name", async ({ name, rules, source }) => {
    const [result] = await eslint.lintText(source, {
      filePath: join(import.meta.dirname, "..", "..", "audit", `${name.replaceAll(" ", "-")}.ts`),
    });
    expect(result?.messages.map(({ ruleId }) => ruleId)).toEqual(rules);
  });
});
