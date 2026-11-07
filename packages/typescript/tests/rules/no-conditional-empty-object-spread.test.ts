// vitest: shared-module-graph
import rule from "../../src/rules/no-conditional-empty-object-spread.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester();

RULE_TESTER.run("no-conditional-empty-object-spread", rule, {
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
      code: "const value = { ...(enabled ? { a: 1 } : {}) };", output: "const value = { ...(!!(enabled) && ({ a: 1 })) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { ...(enabled ? {} : { a: 1 }) };", output: "const value = { ...(!(enabled) && ({ a: 1 })) };",
      errors: [
        {
          messageId: "avoid",
        },
      ],
    },
    {
      code: "const value = { ...((enabled ? { a: 1 } : {})) };", output: "const value = { ...((!!(enabled) && ({ a: 1 }))) };",
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
