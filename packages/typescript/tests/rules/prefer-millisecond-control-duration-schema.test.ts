import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_MILLISECOND_CONTROL_DURATION_SCHEMA_DOCUMENTATION,
} from "../../src/rules/prefer-millisecond-control-duration-schema.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();
const ERROR = { messageId: "preferMilliseconds" as const };
const zod = (code: string): string => `import { z } from "zod";\n${code}`;

RULE_TESTER.run("prefer-millisecond-control-duration-schema", rule, {
  valid: [
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
