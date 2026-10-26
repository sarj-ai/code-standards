// vitest: shared-module-graph
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
    { name: "preserves implicit declaration-file property contracts", filename: "src/contracts.d.ts", code: "import type { Imported } from './other'; interface Local { user_id: string }" },
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
    { name: "preserves polymorphic this key dependencies", code: "export {}; interface Local { user_id: string; selected: this['user_id'] }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves quoted camelCase collisions", code: "export {}; interface Local { 'userId': number; user_id: string }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves merged interface contracts", code: "export {}; interface Local { user_id: string } interface Local { userId: number }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves computed-key collisions", code: "export {}; const key = 'userId' as const; interface Local { [key]: number; user_id: string }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves template index constraints", code: "export {}; interface Local { [key: `userI${string}`]: number; user_id: string }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "renames an unused private interface property", code: "export {}; interface Local { user_id: string }", output: "export {}; interface Local { userId: string }", errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "renames an unused private object type property", code: "export {}; type Local = { user_id: string }", output: "export {}; type Local = { userId: string }", errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves a referenced wire contract", code: "interface Local { user_id: string } const value: Local = input;", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves a conflicting camelCase property", code: "export {}; interface Local { user_id: string; userId: number }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
    { name: "preserves inherited property contracts", code: "export {}; interface Base { userId: number } interface Local extends Base { user_id: string }", output: null, errors: [{ messageId: "requireCamelcaseProperty" }] },
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
