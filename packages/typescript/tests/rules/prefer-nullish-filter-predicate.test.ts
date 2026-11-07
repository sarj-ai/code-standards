import { runInNewContext } from "node:vm";

import { expect, it } from "vitest";

import rule from "../../src/rules/prefer-nullish-filter-predicate.js";
import { FIXTURES, ruleTester, typed } from "./_tester.js";

const EXPLICIT_PREDICATE_EXAMPLE =
  "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter((user) => user !== null && user !== undefined);";
const BOOLEAN_FILTER_EXAMPLE = "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter(Boolean);";
const AUTOFIX_SOURCE = "const present = [{ id: 'kept' }, null].filter(Boolean);";
const AUTOFIX_FIXED = "const present = [{ id: 'kept' }, null].filter((value) => value !== null && value !== undefined);";

const RULE_TESTER = ruleTester({ cwd: FIXTURES });

function oneSuggestion(code: string, parameter = "value", undefinedCheck = `${parameter} !== undefined`) {
  return [{ messageId: "replaceBoolean", output: code.replace("(Boolean)", `((${parameter}) => ${parameter} !== null && ${undefinedCheck})`) }];
}

RULE_TESTER.run("prefer-nullish-filter-predicate", rule, typed({
  valid: [
    { name: "preserves the browser's falsy document.all object", code: "declare const values: readonly (HTMLAllCollection | null)[]; values.filter(Boolean);" },
    { name: "preserves structural supertypes of the browser's falsy object", code: "declare const values: readonly (Pick<HTMLAllCollection, 'length' | 'item'> | null)[]; values.filter(Boolean);" },
    {
      name: "accepts the documented explicit predicate",
      code: EXPLICIT_PREDICATE_EXAMPLE,
    },
    "declare const values: readonly (string | null)[]; values.filter(Boolean);",
    "declare const values: readonly (0 | { id: string } | null)[]; values.filter(Boolean);",
    "declare const values: readonly (false | { id: string } | null)[]; values.filter(Boolean);",
    "declare const values: readonly (unknown | null)[]; values.filter(Boolean);",
    "declare const values: readonly (any | null)[]; values.filter(Boolean);",
    "declare const values: readonly (void | null)[]; values.filter(Boolean);",
    "declare const values: readonly ({} | null)[]; values.filter(Boolean);",
    "declare const values: readonly ({ id: string } | null)[]; const Boolean = (x: unknown) => true; values.filter(Boolean);",
    "declare const values: { filter(callback: typeof Boolean): unknown }; values.filter(Boolean);",
    "declare const values: readonly ({ id: string } | null)[]; values.filter((value) => value !== null && value !== undefined);",
    { name: "documented example boolean-nullish-filter-dynamic-member", filename: "src/users.ts", code: "declare const users: readonly ({ id: string } | null)[];\nconst present = users[auditDynamicMember](Boolean);" },
  ],
  invalid: [
    { name: "fixes a fresh inert literal array with no preceding callouts", code: AUTOFIX_SOURCE, output: AUTOFIX_FIXED, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion(AUTOFIX_SOURCE) }] },
    { name: "fixes an isolated fresh literal expression", code: "[{ id: 'kept' }, null].filter(Boolean);", output: "[{ id: 'kept' }, null].filter((value) => value !== null && value !== undefined);", errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("[{ id: 'kept' }, null].filter(Boolean);") }] },
    { name: "retains externally supplied receivers whose filter can observe callback identity", code: "function present(values: readonly ({ id: string } | null)[]) { return values.filter(Boolean); }", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("function present(values: readonly ({ id: string } | null)[]) { return values.filter(Boolean); }") }] },
    { name: "retains fresh arrays after a source prototype replacement", code: "Array.prototype.filter = replacement; const present = [{ id: 'kept' }, null].filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("Array.prototype.filter = replacement; const present = [{ id: 'kept' }, null].filter(Boolean);") }] },
    { name: "retains fresh arrays after an arbitrary import", code: "import './patch-array.js'; const present = [{ id: 'kept' }, null].filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("import './patch-array.js'; const present = [{ id: 'kept' }, null].filter(Boolean);") }] },
    { name: "retains effectful element initialization", code: "const present = [{ id: read() }, null].filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("const present = [{ id: read() }, null].filter(Boolean);") }] },
    { name: "preserves filtering with a shadowed undefined binding", code: "function present(undefined: object, values: readonly ({ id: string } | null | undefined)[]) { return values.filter(Boolean); }", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("function present(undefined: object, values: readonly ({ id: string } | null | undefined)[]) { return values.filter(Boolean); }", "value", "typeof value !== \"undefined\"") }] },
    { name: "chooses a fresh callback name when common names are bound", code: "declare const value: string, item: string, element: string, candidate: string; declare const values: readonly (true | null)[]; values.filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("declare const value: string, item: string, element: string, candidate: string; declare const values: readonly (true | null)[]; values.filter(Boolean);", "value1") }] },
    {
      name: "reports the documented object-null union",
      code: BOOLEAN_FILTER_EXAMPLE, output: null,
      errors: [
        {
          messageId: "preferNullishPredicate",
          suggestions: [
            {
              messageId: "replaceBoolean",
              output:
                "declare const users: readonly ({ id: string } | null)[];\nconst present = users.filter((value) => value !== null && value !== undefined);",
            },
          ],
        },
      ],
    },
    {
      code: "declare const values: readonly (true | null | undefined)[]; values.filter(Boolean);", output: null,
      errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("declare const values: readonly (true | null | undefined)[]; values.filter(Boolean);") }],
    },
    {
      code: "declare const values: readonly ('ready' | null)[]; values.filter(Boolean);", output: null,
      errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("declare const values: readonly ('ready' | null)[]; values.filter(Boolean);") }],
    },
    {
      code: "declare const values: readonly (42 | null)[]; values.filter(Boolean);", output: null,
      errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("declare const values: readonly (42 | null)[]; values.filter(Boolean);") }],
    },
    { name: "documented example boolean-nullish-filter-static-member", filename: "src/users.ts", code: "declare const users: readonly ({ id: string } | null)[];\nconst present = users[\"filter\"](Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: oneSuggestion("declare const users: readonly ({ id: string } | null)[];\nconst present = users[\"filter\"](Boolean);") }] },
  ],
}));

RULE_TESTER.run("prefer-nullish-filter-predicate without types", rule, {
  valid: [{ name: "returns no visitors without type information", code: BOOLEAN_FILTER_EXAMPLE, settings: { sarj: { typeAware: false } } }],
  invalid: [],
});

it("preserves fresh literal filtering with canonical built-in methods", () => {
  expect(runInNewContext(`${AUTOFIX_FIXED}\nJSON.stringify(present);`)).toBe(
    runInNewContext(`${AUTOFIX_SOURCE}\nJSON.stringify(present);`),
  );
});
