import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION,
} from "../../src/rules/require-interface-for-exported-class.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: { parser: tsParser, sourceType: "module" },
});

RULE_TESTER.run("require-interface-for-exported-class", rule, {
  valid: [
    REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[0].files[0]
      .source,
    "export abstract class ArtifactStore { abstract read(id: string): Promise<Uint8Array>; }",
    "export class ArtifactStore extends BaseStore { read() {} }",
    "export class ArtifactRecord { constructor(readonly id: string) {} }",
    "class InternalStore { read() {} } export { InternalStore };",
    {
      filename: "src/artifact-store.test.ts",
      code: "export class ArtifactStore { read() {} }",
    },
  ],
  invalid: [
    {
      code: REQUIRE_INTERFACE_FOR_EXPORTED_CLASS_DOCUMENTATION.examples[1]
        .files[0].source,
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "export default class { run = () => undefined; }",
      errors: [{ messageId: "requireContract", data: { name: "default" } }],
    },
  ],
});
