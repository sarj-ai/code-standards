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
    "abstract class BaseStore { abstract read(): void; } export class ArtifactStore extends BaseStore { read() {} }",
    "abstract class BaseStore { abstract read(): void; } export const ArtifactStore = class extends BaseStore { read() {} };",
    "interface Storage { read(): void; } export const ArtifactStore = class implements Storage { read() {} };",
    "export class ArtifactRecord { constructor(readonly id: string) {} }",
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
    {
      code: "class InternalStore { read() {} } export { InternalStore };",
      errors: [{ messageId: "requireContract", data: { name: "InternalStore" } }],
    },
    {
      code: "class ArtifactStore { read() {} } export default ArtifactStore;",
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "class BaseStore { read() {} } export class ArtifactStore extends BaseStore { read() {} }",
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "export class ArtifactStore { get current() { return 'value'; } }",
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "export const ArtifactStore = class { read() {} };",
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "const InternalStore = class { read() {} }; export { InternalStore as ArtifactStore };",
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "const ArtifactStore = class { read() {} }; export default ArtifactStore;",
      errors: [{ messageId: "requireContract", data: { name: "ArtifactStore" } }],
    },
    {
      code: "export default class { get current() { return 'value'; } }",
      errors: [{ messageId: "requireContract", data: { name: "default" } }],
    },
  ],
});
