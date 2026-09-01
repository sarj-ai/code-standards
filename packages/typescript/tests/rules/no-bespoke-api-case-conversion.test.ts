import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION,
} from "../../src/rules/no-bespoke-api-case-conversion.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();
const ERROR = { messageId: "noBespokeApiCaseConversion" as const };
const adapter = (body: string): string =>
  `import type { Contract } from "./api-contract";\n${body}`;

RULE_TESTER.run("no-bespoke-api-case-conversion", rule, {
  valid: [
    {
      name: "accepts the documented generated-client surface",
      filename: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[0].focusPath,
      code: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[0].files[0].source,
    },
    {
      name: "ignores ordinary domain files",
      filename: "/repo/src/user.ts",
      code: adapter("const user = { displayName: raw.display_name };"),
    },
    {
      name: "requires a proven API boundary import",
      filename: "/repo/src/user-adapter.ts",
      code: 'import type { User } from "./domain"; const user = { displayName: raw.display_name };',
    },
    {
      name: "ignores unrelated names instead of guessing intent",
      filename: "/repo/src/user-adapter.ts",
      code: adapter("const user = { displayName: raw.legal_name };"),
    },
    {
      name: "preserves quoted protocol keys",
      filename: "/repo/src/user-adapter.ts",
      code: adapter('const wire = { "display_name": user.displayName };'),
    },
    {
      name: "preserves computed protocol keys",
      filename: "/repo/src/user-adapter.ts",
      code: adapter("const wire = { [wireName]: user.displayName };"),
    },
    {
      name: "ignores generated adapters",
      filename: "/repo/src/generated/user-adapter.ts",
      code: adapter("const user = { displayName: raw.display_name };"),
    },
    {
      name: "ignores adapter tests and fixtures",
      filename: "/repo/src/fixtures/user-adapter.ts",
      code: adapter("const user = { displayName: raw.display_name };"),
    },
    {
      name: "does not confuse strings and comments for object properties",
      filename: "/repo/src/user-adapter.ts",
      code: adapter('const note = "displayName: raw.display_name"; // displayName: raw.display_name'),
    },
  ],
  invalid: [
    {
      name: "reports the documented read conversion",
      filename: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[1].focusPath,
      code: NO_BESPOKE_API_CASE_CONVERSION_DOCUMENTATION.examples[1].files[0].source,
      errors: [ERROR],
    },
    {
      name: "reports a write conversion",
      filename: "/repo/src/integration-adapters.ts",
      code: adapter("const wire = { owner_organization_id: draft.ownerOrganizationId };"),
      errors: [ERROR],
    },
    {
      name: "reports each independently maintained mapping",
      filename: "/repo/src/api.adapter.ts",
      code: adapter("const value = { isSecret: raw.is_secret, updatedAt: raw.updated_at };"),
      errors: [ERROR, ERROR],
    },
    {
      name: "recognizes nested member reads",
      filename: "/repo/src/user-adapter.ts",
      code: adapter("const value = { retryIntervalSeconds: raw.settings.retry_interval_seconds };"),
      errors: [ERROR],
    },
  ],
});
