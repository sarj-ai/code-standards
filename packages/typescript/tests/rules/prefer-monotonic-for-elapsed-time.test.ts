// vitest: shared-module-graph
import { expect, it } from "vitest";

import { RULES } from "../../src/catalog.js";
import rule from "../../src/rules/prefer-monotonic-for-elapsed-time.js";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import { ruleTester } from "./_tester.js";

ruleTester().run("prefer-monotonic-for-elapsed-time", rule, {
  valid: [
  "const start = performance.now(); consume(performance.now() - start);",
  "const start = Date.now(); publish(start); consume(Date.now() - start);",
  "export const start = Date.now(); consume(Date.now() - start);",
  "let start = Date.now(); start = other; consume(Date.now() - start);",
  "function run(Date: { now(): number }) { const start = Date.now(); consume(Date.now() - start); }",
  "const timestamp = Date.now(); publish(timestamp);",
  "const start = Date.now(); consume(otherClock() - start);",
  "Date.now = mocked; const start = Date.now(); consume(Date.now() - start);",
  "const start = Date.now(); change(Date); consume(Date.now() - start);",
  "const start = Date.now(); const elapsed = start - Date.now();"
],
  invalid: [
  {
    "code": "const start = Date.now(); consume(Date.now() - start);",
    "errors": [
      {
        "messageId": "preferMonotonicForElapsedTime"
      }
    ]
  },
  {
    "code": "async function run() { const start = Date.now(); await work(); return Date.now() - start; }",
    "errors": [
      {
        "messageId": "preferMonotonicForElapsedTime"
      }
    ]
  },
  {
    "code": "const start = Date.now(); consume(Date.now() - start); consume(Date.now() - start);",
    "errors": [
      {
        "messageId": "preferMonotonicForElapsedTime"
      }
    ]
  },
  {
    "code": "const start = (Date.now()); consume((Date.now()) - (start));",
    "errors": [
      {
        "messageId": "preferMonotonicForElapsedTime"
      }
    ]
  }
],
});

it("executes the documented examples", async () => {
  await expect(verifyRuleExamples(RULES["prefer-monotonic-for-elapsed-time"])).resolves.toBeGreaterThan(0);
});
