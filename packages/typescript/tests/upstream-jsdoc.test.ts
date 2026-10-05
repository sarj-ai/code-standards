import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import jsdoc from "../src/upstream/jsdoc.js";

RuleTester.describe = describe;
RuleTester.it = it;
const tester = new RuleTester({
  languageOptions: { parserOptions: { lang: "ts" } },
});
const permitTypes = (code: string) => ({
  code,
  options: [{ allowTypedContracts: true }],
});
const error = { messageId: "implementation" };

tester.run(
  "jsdoc/no-implementation-jsdoc",
  jsdoc.rules["no-implementation-jsdoc"],
  {
    valid: [
      "function run() {}",
      "/** Public contract. */ interface Handler { run(): void }",
      "/** Public contract. */ declare function run(): void;",
      "// Explains the vendor mismatch.\nfunction run() {}",
      "/** File overview. */\n\nfunction run() {}",
      "function run() { /** Describes a local constant. */ const value = 1; }",
      permitTypes(
        "/** @param {string} value\n * @returns {number} */ export const run = (value) => value.length;",
      ),
      permitTypes("/** @returns {number} */ function run() { return 1; }"),
      permitTypes("/** @param {string} value */ const run = (value) => value;"),
      permitTypes(
        "/** @template T */ const run = function(value) { return value; };",
      ),
    ],
    invalid: [
      { code: "/** Run the function. */ function run() {}", errors: [error] },
      {
        code: "/** Run the function. */ const run = () => 1;",
        errors: [error],
      },
      {
        code: "/** Run the function. */ const run = function() {};",
        errors: [error],
      },
      {
        code: "/** @returns {number} */ export function run() { return 1; }",
        errors: [error],
      },
      {
        ...permitTypes("/** Run the function. */ function run() {}"),
        errors: [error],
      },
      {
        ...permitTypes("/** @returns {string |} */ function run() {}"),
        errors: [error],
      },
    ],
  },
);
