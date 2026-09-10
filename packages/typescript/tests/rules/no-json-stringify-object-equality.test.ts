import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION,
} from "../../src/rules/no-json-stringify-object-equality.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*", "*/*.ts*", "*/*/*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});
const PRODUCTION = "json-object-equality.ts";

RULE_TESTER.run("no-json-stringify-object-equality", rule, {
  valid: [
    {
      name: "accepts the documented domain comparator",
      filename: PRODUCTION,
      code: NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION.examples[0].files[0].source,
    },
    { name: "allows serialization for persistence", filename: PRODUCTION, code: "const stored = JSON.stringify(value);" },
    { name: "allows one-sided text comparison", filename: PRODUCTION, code: "const same = JSON.stringify(value) === stored;" },
    { name: "allows primitive string arrays", filename: PRODUCTION, code: "declare const left: string[]; declare const right: readonly string[]; const same = JSON.stringify(left) === JSON.stringify(right);" },
    { name: "allows primitive tuples", filename: PRODUCTION, code: "declare const left: readonly [string, number]; declare const right: [string, number]; const same = JSON.stringify(left) === JSON.stringify(right);" },
    { name: "allows literal primitive arrays without type services", code: "const same = JSON.stringify(['a', 1]) === JSON.stringify(['a', 1]);" },
    { name: "allows a shadowed JSON object", filename: PRODUCTION, code: "function compare(JSON: Serializer, left: object, right: object) { return JSON.stringify(left) === JSON.stringify(right); }" },
    { name: "allows a structural helper", filename: PRODUCTION, code: "const same = sameJson(left, right);" },
    { name: "ignores tests", filename: "compare.test.ts", code: "expect(JSON.stringify(actual)).toBe(JSON.stringify(expected));" },
    { name: "ignores generated files", filename: "generated/compare.ts", code: "const same = JSON.stringify({a: 1}) === JSON.stringify({a: 1});" },
  ],
  invalid: [
    {
      name: "reports the documented object comparison",
      filename: PRODUCTION,
      code: NO_JSON_STRINGIFY_OBJECT_EQUALITY_DOCUMENTATION.examples[1].files[0].source,
      errors: [{ messageId: "serializedObjectEquality" }],
    },
    { name: "reports reordered object properties", filename: PRODUCTION, code: "const same = JSON.stringify({ event_type: 'a', event_payload: {} }) === JSON.stringify({ event_payload: {}, event_type: 'a' });", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports object variables", filename: PRODUCTION, code: "declare const actual: { id: string }; declare const expected: { id: string }; const same = JSON.stringify(actual) !== JSON.stringify(expected);", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports arrays containing objects", filename: PRODUCTION, code: "declare const actual: Array<{ id: string }>; declare const expected: Array<{ id: string }>; const same = JSON.stringify(actual) === JSON.stringify(expected);", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports unknown values", filename: PRODUCTION, code: "declare const actual: unknown; declare const expected: unknown; const same = JSON.stringify(actual) == JSON.stringify(expected);", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports undefined-collapsing object comparison", filename: PRODUCTION, code: "const same = JSON.stringify({ value: undefined }) === JSON.stringify({});", errors: [{ messageId: "serializedObjectEquality" }] },
  ],
});
