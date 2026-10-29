// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION } from "../../src/rules/no-mutating-input-with-result.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parser } });

TESTER.run("no-mutating-input-with-result", rule, {
  valid: [
    NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION.examples[1].files[0].source,
    { name: "void command", code: "function enable(config: { enabled: boolean }): void { config.enabled = true; }" },
    { name: "async void command", code: "async function enable(config: { enabled: boolean }): Promise<void> { config.enabled = true; }" },
    { name: "receiver state belongs to its owner", code: "class Counter { value = 0; increment(): number { this.value++; return this.value; } }" },
    { name: "copy then change", code: "function enable(config: { enabled: boolean }): boolean { const result = { ...config }; result.enabled = true; return result.enabled; }" },
    { name: "parameter rebound to fresh value", code: "function enable(config: { enabled: boolean }): boolean { config = { enabled: false }; config.enabled = true; return true; }" },
    { name: "readonly writes are compiler-owned", code: "function enable(config: { readonly enabled: boolean }): boolean { config.enabled = true; return true; }" },
    { name: "array ownership has a separate rule", code: "function enable(config: boolean[]): boolean[] { config[0] = true; return config; }" },
    { name: "nested callback owns its command", code: "function enable(config: { enabled: boolean }): boolean { register(() => { config.enabled = true; }); return true; }" },
    { name: "nested descendant is outside direct contract", code: "function enable(config: { child: { enabled: boolean } }): boolean { config.child.enabled = true; return true; }" },
    { name: "imported domain is unresolved", code: "import { Config } from './config.js'; function enable(config: Config): boolean { config.enabled = true; return true; }" },
    { name: "throw-only body has no result", code: "function enable(config: { enabled: boolean }): boolean { config.enabled = true; throw new Error('failed'); }" },
    { name: "return makes later write unreachable", code: "function enable(config: { enabled: boolean }): boolean { return true; config.enabled = true; }" },
    { name: "literal false never writes", code: "function enable(config: { enabled: boolean }): boolean { if (false) config.enabled = true; return true; }" },
    { name: "short circuit never writes", code: "function enable(config: { enabled: boolean }): boolean { false && (config.enabled = true); return true; }" },
    { name: "generated artifact", filename: "src/generated/config.ts", code: NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION.examples[0].files[0].source },
    { name: "local suppression", code: "function enable(config: { enabled: boolean }): boolean {\n// eslint-disable-next-line @rule-tester/no-mutating-input-with-result -- callback contract intentionally reports its mutation\nconfig.enabled = true; return true; }" },
  ],
  invalid: [
    { code: NO_MUTATING_INPUT_WITH_RESULT_DOCUMENTATION.examples[0].files[0].source, errors: [{ messageId: "inputWrite" }] },
    ...[
      ["inline object contract", "function enable(config: { enabled: boolean }): boolean { config.enabled = true; return true; }"],
      ["named model class", "class Config { enabled = false; } function enable(config: Config): Config { config.enabled = true; return config; }"],
      ["object alias", "type Config = { enabled: boolean }; function enable(config: Config): Config { config.enabled = true; return config; }"],
      ["property increment", "function increment(config: { version: number }): number { return config.version++; }"],
      ["property deletion", "function clear(config: { version?: number }): boolean { delete config.version; return true; }"],
      ["implicit arrow result", "const enable = (config: { enabled: boolean }): boolean => config.enabled = true;"],
      ["async result", "async function enable(config: { enabled: boolean }): Promise<boolean> { config.enabled = true; return true; }"],
    ].map(([name, code]) => ({ name, code, errors: [{ messageId: "inputWrite" as const }] })),
  ],
});
