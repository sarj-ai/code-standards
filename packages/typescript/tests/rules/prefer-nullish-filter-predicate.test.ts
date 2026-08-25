import { join } from "node:path";

import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, {
  PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION,
} from "../../src/rules/prefer-nullish-filter-predicate.js";

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
    {
      name: "reports the documented object-null union",
      code: PREFER_NULLISH_FILTER_PREDICATE_DOCUMENTATION.examples[1].files[0].source,
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
      code: "declare const values: readonly (true | null | undefined)[]; values.filter(Boolean);",
      errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }],
    },
    {
      code: "declare const values: readonly ('ready' | null)[]; values.filter(Boolean);",
      errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }],
    },
    {
      code: "declare const values: readonly (42 | null)[]; values.filter(Boolean);",
      errors: [{ messageId: "preferNullishPredicate", suggestions: 1 }],
    },
  ],
});
