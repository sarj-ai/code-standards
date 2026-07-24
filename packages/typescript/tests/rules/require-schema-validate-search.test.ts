import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/require-schema-validate-search.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("require-schema-validate-search", rule, {
  valid: [
    // The prescribed pattern: schema validator, no casts.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: zodValidator(searchSchema),
        });
      `,
    },
    // Hand-rolled but actually parsing — no casts.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => searchSchema.parse(search),
        });
      `,
    },
    // Coercion without lying casts.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => ({ page: Number(search.page) || 1 }),
        });
      `,
    },
    // `as const` narrows rather than lies — exempt.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => ({ tab: 'all' as const }),
        });
      `,
    },
    // Casts in other properties are no-unsafe-cast's business, not ours.
    {
      code: `
        const route = createFileRoute('/calls')({
          loader: () => data as CallData,
        });
      `,
    },
    // A validateSearch that is not a function (adapter object) is out of scope.
    {
      code: "const opts = { validateSearch: adapter };",
    },
    // The rule's own recommended remedy: a cast that feeds a runtime
    // validator is validated regardless — parse/safeParse/decode arguments
    // are exempt, however deeply the cast nests.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (s) => schema.parse(s as Record<string, unknown>),
        });
      `,
    },
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (s) => searchSchema.safeParse(s as Record<string, unknown>).data,
        });
      `,
    },
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (s) => codec.decode(normalize(s as Raw)),
        });
      `,
    },
    // Angle-bracket const assertion narrows rather than lies — exempt.
    {
      code: "const opts = { validateSearch: (s) => ({ tab: <const>'all' }) };",
    },
    // Test files are exempt (route stubs are fixtures, not real routes).
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => search as CallsSearch,
        });
      `,
      filename: "/repo/src/routes/calls.test.ts",
    },
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => search as CallsSearch,
        });
      `,
      filename: "/repo/src/routes/__tests__/calls.ts",
    },
  ],
  invalid: [
    // The mined pattern: cast the raw search params and call it validated.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => search as CallsSearch,
        });
      `,
      errors: [{ messageId: "castInValidateSearch" }],
    },
    // Cast on a field inside the returned object.
    {
      code: `
        const route = createFileRoute('/calls')({
          validateSearch: (search) => ({
            page: Number(search.page) || 1,
            status: (search.status as Status) ?? 'all',
          }),
        });
      `,
      errors: [{ messageId: "castInValidateSearch" }],
    },
    // Function-expression form with a block body.
    {
      code: `
        const opts = {
          validateSearch: function (search) {
            return { tab: search.tab as Tab };
          },
        };
      `,
      errors: [{ messageId: "castInValidateSearch" }],
    },
    // String-literal key spelling.
    {
      code: `
        const opts = {
          'validateSearch': (search) => search as Search,
        };
      `,
      errors: [{ messageId: "castInValidateSearch" }],
    },
    // Angle-bracket cast form (`<T>x`) is the same lie as `as`.
    {
      code: `
        const opts = {
          validateSearch: (search) => <CallsSearch>search,
        };
      `,
      errors: [{ messageId: "castInValidateSearch" }],
    },
    // A cast on the validator callee's receiver is NOT the validated-argument
    // exemption — only arguments of parse/safeParse/decode are exempt.
    {
      code: `
        const opts = {
          validateSearch: (s) => (schema as AnySchema).parse(s),
        };
      `,
      errors: [{ messageId: "castInValidateSearch" }],
    },
  ],
});
