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
    { name: "does not infer a serializer destructured from an unknown object", filename: PRODUCTION, code: "const { stringify } = serializer; const same = stringify({a: 1}) === stringify({a: 1});" },
    { name: "does not infer a serializer destructured from shadowed JSON", filename: PRODUCTION, code: "function compare(JSON: Serializer) { const { stringify } = JSON; return stringify({a: 1}) === stringify({a: 1}); }" },
    { name: "does not follow a shadowed alias parameter", filename: PRODUCTION, code: "const { stringify } = JSON; function compare(stringify: Serializer) { return stringify({a: 1}) === stringify({a: 1}); }" },
    { name: "does not follow mutable destructured bindings", filename: PRODUCTION, code: "let { stringify } = JSON; const same = stringify({a: 1}) === stringify({a: 1});" },
    { name: "does not follow a destructured alias with later writes", filename: PRODUCTION, code: "const { stringify } = JSON; stringify = canonical; const same = stringify({a: 1}) === stringify({a: 1});" },
    { name: "does not follow defaulted destructuring", filename: PRODUCTION, code: "const { stringify = canonical } = JSON; const same = stringify({a: 1}) === stringify({a: 1});" },
    { name: "does not infer transitive serializer aliases", filename: PRODUCTION, code: "const { stringify } = JSON; const serialize = stringify; const same = serialize({a: 1}) === serialize({a: 1});" },
    { name: "preserves primitive array exclusion through a native alias", filename: PRODUCTION, code: "declare const left: string[]; declare const right: readonly string[]; const { stringify: serialize } = JSON; const same = serialize(left) === serialize(right);" },
    { name: "preserves primitive literal array exclusion through a native alias", code: "const { stringify } = JSON; const same = stringify(['a', 1]) === stringify(['a', 1]);" },
    { name: "preserves one-sided alias serialization", filename: PRODUCTION, code: "const { stringify } = JSON; const same = stringify({a: 1}) === stored;" },

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
    { name: "allows a shadowed computed JSON object", filename: PRODUCTION, code: "function compare(JSON: Serializer, left: object, right: object) { return JSON['stringify'](left) === JSON['stringify'](right); }" },
    { name: "allows a structural helper", filename: PRODUCTION, code: "const same = sameJson(left, right);" },
    { name: "ignores tests", filename: "compare.test.ts", code: "expect(JSON.stringify(actual)).toBe(JSON.stringify(expected));" },
    { name: "ignores generated files", filename: "generated/compare.ts", code: "const same = JSON.stringify({a: 1}) === JSON.stringify({a: 1});" },
  ],
  invalid: [
    { name: "reports stable const destructured native stringify", filename: PRODUCTION, code: "const { stringify } = JSON; const same = stringify({a: 1}) === stringify({a: 1});", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports a renamed native stringify binding", filename: PRODUCTION, code: "const { stringify: serialize } = JSON; const same = serialize({a: 1}) !== serialize({a: 1});", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports a statically computed native destructuring key", filename: PRODUCTION, code: "const { ['stringify']: serialize } = JSON; const same = serialize({a: 1}) === serialize({a: 1});", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports a native alias compared with a direct call", filename: PRODUCTION, code: "const { stringify } = JSON; const same = stringify({a: 1}) === JSON.stringify({a: 1});", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports object variables through a native serializer alias", filename: PRODUCTION, code: "declare const left: {id: string}; declare const right: {id: string}; const { stringify } = JSON; const same = stringify(left) === stringify(right);", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "reports aliases scoped inside a production function", filename: PRODUCTION, code: "function compare() { const { stringify } = JSON; return stringify({a: 1}) === stringify({a: 1}); }", errors: [{ messageId: "serializedObjectEquality" }] },
    { name: "preserves native alias provenance through erased wrappers", filename: PRODUCTION, code: "const { stringify } = (JSON satisfies JSON); const same = (stringify as typeof JSON.stringify)({a: 1}) === stringify({a: 1});", errors: [{ messageId: "serializedObjectEquality" }] },

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
    { name: "reports computed native stringify access", filename: PRODUCTION, code: "declare const actual: { id: string }; declare const expected: { id: string }; const same = JSON['stringify'](actual) === JSON['stringify'](expected);", errors: [{ messageId: "serializedObjectEquality" }] },
  ],
});
