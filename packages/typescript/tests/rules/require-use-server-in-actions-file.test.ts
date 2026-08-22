import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-use-server-in-actions-file.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

RULE_TESTER.run("require-use-server-in-actions-file", rule, {
  valid: [
    { filename: "/repo/app/orders/actions.ts", code: "'use server'; export async function save() {}" },
    { filename: "/repo/app/orders/order-actions.ts", code: "'use server'; export const save = async () => {};" },
    { filename: "/repo/lib/actions.ts", code: "export async function save() {}" },
    { filename: "/repo/app/orders/helpers.ts", code: "export async function save() {}" },
    { filename: "/repo/app/orders/actions.ts", code: "export function format() {}" },
    { filename: "/repo/app/orders/actions.ts", code: "async function save() {} export { save };" },
  ],
  invalid: [
    {
      filename: "/repo/app/orders/actions.ts",
      code: "export async function save() {}",
      errors: [{ messageId: "requireUseServerInActionsFile" }],
    },
    {
      filename: "C:\\repo\\app\\orders\\order-actions.ts",
      code: "export const save = async () => {};",
      errors: [{ messageId: "requireUseServerInActionsFile" }],
    },
  ],
});
