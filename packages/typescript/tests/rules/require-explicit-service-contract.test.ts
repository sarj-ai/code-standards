import { it } from "vitest";
import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/require-explicit-service-contract.js";

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe } from "vitest";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.itOnly = it.only;
RuleTester.it = it;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  },
});

RULE_TESTER.run("require-explicit-service-contract", rule, {
  valid: [
    "interface Runner { run(): void } class Service implements Runner { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
    "class Service { constructor(private readonly metadata: Metadata) {} id() { return this.metadata.id; } }",
    "abstract class Runner { abstract run(): void } class Service extends Runner { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }",
    "class Service { constructor(private readonly worker: Worker) {} run() { if (false) return this.worker.run(); } }",
  ],
  invalid: [
    {
      code: "class Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    {
      code: "interface Service { run(): void } class Service { constructor(private readonly worker: Worker) {} run() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    {
      code: "class Unrelated { nothing() {} } class Service extends Unrelated { constructor(private readonly worker: Worker) { super(); } run() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
    {
      code: "class Service { constructor(private readonly worker: Worker) {} run() { this.helper(); } private helper() { this.worker.run(); } }",
      errors: [{ messageId: "requireExplicitServiceContract" }],
    },
  ],
});
