import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION,
} from "../../src/rules/require-camelcase-properties.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();
const ERROR = { messageId: "requireCamelcaseProperty" as const };

RULE_TESTER.run("require-camelcase-properties", rule, {
  valid: [
    {
      name: "accepts the documented application property",
      filename: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION.examples[0].focusPath,
      code: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "keeps quoted wire keys explicit",
      code: 'type Wire = { "date_from": string }; const wire: Wire = { "date_from": value }; wire["date_from"];',
    },
    {
      name: "keeps computed, numeric, and symbol keys explicit",
      code: "declare const wireKey: unique symbol; const value = { [wireKey]: 1, [field]: 2, 0: 3 };",
    },
    {
      name: "accepts camelCase declarations, methods, accessors, and reads",
      code: "interface Range { dateFrom: string; readValue(): string } class Value { dateFrom = ''; get readValue() { return this.dateFrom; } runTask() {} }",
    },
    {
      name: "ignores generated files",
      filename: "/repo/src/generated/client.ts",
      code: "export type Wire = { date_from: string }; export const wire = { date_from: '' };",
    },
  ],
  invalid: [
    {
      name: "reports the pull-request return shape",
      filename: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION.examples[1].focusPath,
      code: REQUIRE_CAMELCASE_PROPERTIES_DOCUMENTATION.examples[1].files[0].source,
      errors: [ERROR, ERROR],
    },
    {
      name: "reports object literals, destructuring, and dot access",
      code: "const value = { date_from: input }; const { date_from } = value; value.date_from;",
      errors: [ERROR, ERROR, ERROR],
    },
    {
      name: "reports interface and class members",
      code: "interface Wire { date_from: string; read_value(): string } class Value { date_from = ''; get read_value() { return ''; } run_task() {} }",
      errors: [ERROR, ERROR, ERROR, ERROR, ERROR],
    },
  ],
});
