import { join } from "node:path";

import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";
import rule from "../../src/rules/require-explicit-contract-implementation.js";

it("executes the documented examples", async () => {
  await verifyRuleExamples(rule);
});

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const TESTER = new RuleTester({
  languageOptions: {
    parser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

TESTER.run("require-explicit-contract-implementation", rule, {
  valid: [
    "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class Fake implements Publisher { publish() {} } new Consumer(new Fake());",
    "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class Fake { publish() {} } new Consumer(new Fake() as Publisher);",
    "interface Options { name: string } class Consumer { constructor(readonly options: Options) {} } class Fake { name = 'x'; } new Consumer(new Fake());",
  ],
  invalid: [{
    code: "interface Publisher { publish(): void } class Consumer { constructor(readonly publisher: Publisher) {} } class Fake { publish() {} } new Consumer(new Fake());",
    errors: [{ messageId: "declareActualContract" }],
  }],
});
