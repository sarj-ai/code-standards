// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION,
} from "../../src/rules/prefer-millisecond-control-duration-schema.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();
const ERROR = { messageId: "preferMilliseconds" as const };
const zod = (code: string): string => `import { z } from "zod";\n${code}`;

RULE_TESTER.run("prefer-millisecond-control-duration-schema", rule, {
  valid: [
    { name: "does not infer quoted factory imports from a different library", code: 'import { "object" as shape, "number" as numeric } from "other"; const Schema = shape({ timeout_seconds: numeric() });' },
    { name: "does not infer a shadowed quoted factory binding", code: 'import { "strictObject" as shape, "number" as numeric } from "zod"; function build(shape: Builder) { return shape({ timeout_seconds: numeric() }); }' },
    { name: "preserves nonnumeric feature flags", code: zod("const Schema = z.object({ timeoutSeconds: z.boolean() });") },
    { name: "preserves unrelated string contracts", code: zod("const Schema = z.object({ timeoutSeconds: z.string().optional() });") },
    { name: "does not infer an unknown schema alias", code: zod("const Schema = z.object({ timeoutSeconds: customSchema });") },
    {
      name: "accepts the documented millisecond field",
      filename: PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION.examples[0].focusPath,
      code: PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION.examples[0].files[0].source,
    },
    { code: zod("const Schema = z.object({ timeout_ms: z.number() });") },
    { code: zod("const Schema = z.object({ retryIntervalMs: z.number() });") },
    {
      name: "allows observed duration metrics in seconds",
      code: zod("const InsightSchema = z.object({ duration_seconds: z.number() });"),
    },
    {
      name: "allows business periods whose unit belongs to the domain",
      code: zod("const PolicySchema = z.object({ retention_period_seconds: z.number() });"),
    },
    {
      name: "preserves quoted protocol keys",
      code: zod('const LegacySchema = z.object({ "timeout_seconds": z.number() });'),
    },
    {
      name: "does not treat another library as Zod",
      code: 'import { z } from "zero"; const Schema = z.object({ timeout_seconds: z.number() });',
    },
    {
      name: "does not treat a shadowed binding as Zod",
      code: zod("function build(z: Builder) { return z.object({ timeout_seconds: z.number() }); }"),
    },
    {
      name: "ignores generated schemas",
      filename: "/repo/src/generated/request.ts",
      code: zod("const Schema = z.object({ timeout_seconds: z.number() });"),
    },
    {
      name: "ignores tests and fixtures",
      filename: "/repo/src/fixtures/request.ts",
      code: zod("const Schema = z.object({ timeout_seconds: z.number() });"),
    },
    {
      name: "ignores interface declarations because they are not runtime schemas",
      code: "interface Request { timeoutSeconds: number }",
    },
  ],
  invalid: [
    { name: "supports quoted direct object factory imports", code: 'import { "object" as shape, "number" as numeric } from "zod"; const Schema = shape({ timeout_seconds: numeric() });', errors: [ERROR] },
    { name: "supports quoted direct strict object factory imports", code: 'import { "strictObject" as shape, "number" as numeric } from "zod/v4"; const Schema = shape({ timeout_seconds: numeric() });', errors: [ERROR] },
    {
      name: "reports the documented seconds field",
      filename: PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION.examples[1].focusPath,
      code: PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION.examples[1].files[0].source,
      errors: [ERROR],
    },
    {
      name: "reports camelCase control fields",
      code: zod("const Schema = z.object({ retryIntervalSeconds: z.number() });"),
      errors: [ERROR],
    },
    {
      name: "reports multiple direct control fields without duplicates",
      code: zod("const Schema = z.strictObject({ delay_seconds: z.number(), leaseSeconds: z.number() });"),
      errors: [ERROR, ERROR],
    },
    {
      name: "supports aliased Zod namespace imports",
      code: 'import { z as schema } from "zod/v4"; const Schema = schema.object({ timeout_seconds: schema.number() });',
      errors: [ERROR],
    },
    {
      name: "supports namespace imports",
      code: 'import * as schema from "zod"; const Schema = schema.object({ heartbeat_interval_seconds: schema.number() });',
      errors: [ERROR],
    },
    {
      name: "supports direct object factory imports",
      code: 'import { object as shape, number } from "zod"; const Schema = shape({ backoff_seconds: number() });',
      errors: [ERROR],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "second-timeout-schema-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/request.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/request.ts",
        "source": "import { z } from 'zod';\nexport const RequestSchema = z[\"object\"]({ timeout_seconds: z[\"number\"]()[\"int\"]()[\"min\"](1)[\"max\"](300)[\"default\"](30) });"
      }
    ]
  },
  {
    "id": "second-timeout-schema-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/request.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/request.ts",
        "source": "import { z } from 'zod';\nexport const RequestSchema = z[auditDynamicMember]({ timeout_seconds: z[auditDynamicMember]()[auditDynamicMember]()[auditDynamicMember](1)[auditDynamicMember](300)[auditDynamicMember](30) });"
      }
    ]
  }
] } });
});
