// vitest: shared-module-graph
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/prefer-native-fetch-in-server-actions.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester();

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

RULE_TESTER.run("prefer-native-fetch-in-server-actions", rule, {
  valid: [
    "import ky from 'ky'; export const client = ky.create({});",
    "'use client'; import ky from 'ky';",
    "import ky from 'ky'; 'use server';",
    "'use server'; import type { HTTPError } from 'ky';",
    "'use server'; import { type Options } from 'ky';",
    "'use server'; import { kyLike } from 'ky-like';",
    "'use server'; export async function load(): Promise<Response> { return fetch('https://example.com'); }",
  ],
  invalid: [
    {
      code: "'use server'; import ky from 'ky';",
      errors: [{ messageId: "preferNativeFetchInServerActions" }],
    },
    {
      code: "'use strict'; \"use server\"; import { HTTPError } from 'ky';",
      errors: [{ messageId: "preferNativeFetchInServerActions" }],
    },
    {
      code: "'use server'; import ky from 'ky/distribution/index.js';",
      errors: [{ messageId: "preferNativeFetchInServerActions" }],
    },
  ],
});
