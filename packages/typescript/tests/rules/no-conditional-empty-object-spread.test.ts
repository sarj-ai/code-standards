// vitest: shared-module-graph
import { RuleTester } from "oxlint/plugins-dev";
import { describe, it } from "vitest";
import rule from "../../src/rules/no-conditional-empty-object-spread.js";

RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const TESTER = new RuleTester({ languageOptions: { parserOptions: { lang: "ts" } } });
TESTER.run("no-conditional-empty-object-spread", rule, {
  valid: [
    "const value = { ...(enabled ? { a: 1 } : { b: 2 }) };",
    "const value = { ...input };",
    "const value = [...(enabled ? [] : items)];",
    "consume(...(enabled ? [] : items));",
    "const value = { ...(enabled && { a: 1 }) };",
    'const value = "...(enabled ? value : {})";',
    "// @generated\nconst value = { ...(enabled ? { a: 1 } : {}) };",
  ],
  invalid: [
    {
      code: "const value = { ...(enabled ? { a: 1 } : {}) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { ...(enabled ? {} : { a: 1 }) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { ...((enabled ? { a: 1 } : {})) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { child: { ...(enabled ? input : {}) } };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
  ],
});
