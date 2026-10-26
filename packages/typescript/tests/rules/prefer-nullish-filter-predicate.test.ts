import { join } from "node:path";
import { runInNewContext } from "node:vm";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, expect, it } from "vitest";

import rule, {
  PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION,
} from "../../src/rules/prefer-nullish-filter-predicate.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      projectService: { allowDefaultProject: ["*.ts*"] },
      tsconfigRootDir: join(import.meta.dirname, "..", "fixtures"),
    },
  },
});

RULE_TESTER.run("prefer-nullish-filter-predicate", rule, {
  valid: [
    { name: "preserves the browser's falsy document.all object", code: "declare const values: readonly (HTMLAllCollection | null)[]; values.filter(Boolean);" },
    { name: "preserves structural supertypes of the browser's falsy object", code: "declare const values: readonly (Pick<HTMLAllCollection, 'length' | 'item'> | null)[]; values.filter(Boolean);" },
    {
      name: "accepts the documented explicit predicate",
      code: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.examples[0].files[0].source,
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
  ],
  invalid: [
    { name: "fixes a fresh inert literal array with no preceding callouts", code: "const present = [{ id: 'kept' }, null].filter(Boolean);", output: "const present = [{ id: 'kept' }, null].filter((value) => value !== null && value !== undefined);", errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "fixes an isolated fresh literal expression", code: "[{ id: 'kept' }, null].filter(Boolean);", output: "[{ id: 'kept' }, null].filter((value) => value !== null && value !== undefined);", errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "retains externally supplied receivers whose filter can observe callback identity", code: "function present(values: readonly ({ id: string } | null)[]) { return values.filter(Boolean); }", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "retains fresh arrays after a source prototype replacement", code: "Array.prototype.filter = replacement; const present = [{ id: 'kept' }, null].filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "retains fresh arrays after an arbitrary import", code: "import './patch-array.js'; const present = [{ id: 'kept' }, null].filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "retains effectful element initialization", code: "const present = [{ id: read() }, null].filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "preserves filtering with a shadowed undefined binding", code: "function present(undefined: object, values: readonly ({ id: string } | null | undefined)[]) { return values.filter(Boolean); }", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    { name: "chooses a fresh callback name when common names are bound", code: "declare const value: string, item: string, element: string, candidate: string; declare const values: readonly (true | null)[]; values.filter(Boolean);", output: null, errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }] },
    {
      name: "reports the documented object-null union",
      code: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.examples[1].files[0].source, output: null,
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
      errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }],
    },
    {
      code: "declare const values: readonly ('ready' | null)[]; values.filter(Boolean);", output: null,
      errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }],
    },
    {
      code: "declare const values: readonly (42 | null)[]; values.filter(Boolean);", output: null,
      errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }],
    },
  ],
});

it("preserves fresh literal filtering with canonical built-in methods", () => {
  const example = PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.examples[2];
  const source = example.files[0].source;
  const fixed = example.fixedFiles[0].source;
  expect(runInNewContext(`${fixed}\nJSON.stringify(present);`)).toBe(
    runInNewContext(`${source}\nJSON.stringify(present);`),
  );
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "boolean-nullish-filter-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/users.ts",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/users.ts",
        "source": "declare const users: readonly ({ id: string } | null)[];\nconst present = users[\"filter\"](Boolean);"
      }
    ]
  },
  {
    "id": "boolean-nullish-filter-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/users.ts",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/users.ts",
        "source": "declare const users: readonly ({ id: string } | null)[];\nconst present = users[auditDynamicMember](Boolean);"
      }
    ]
  }
] } });
});
