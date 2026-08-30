import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule, { PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION } from "../../src/rules/prefer-switch-for-repeated-equality.js";
RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const RULE_TESTER = new RuleTester({ languageOptions: { parser: tsParser, parserOptions: { ecmaVersion: 2024 }, sourceType: "module" } });

RULE_TESTER.run("prefer-switch-for-repeated-equality", rule, {
  valid: [
    "if (kind === 'a') a(); else if (kind === 'b') b();",
    "if (kind === 'a') a(); else if (other === 'b') b(); else if (kind === 'c') c();",
    "if (score > 90) a(); else if (score > 80) b(); else if (score > 70) c();",
    "switch (kind) { case 'a': a(); break; case 'b': b(); break; case 'c': c(); break; }",
  ],
  invalid: [
    {
      code: "if (kind === 'a') a(); else if ('b' === kind) b(); else if (kind === 'c') c(); else fallback();",
      errors: [{ messageId: "preferSwitch", data: { discriminant: "kind" } }],
    },
    {
      code: "if (kind === Kind.A) a(); else if (Kind.B === kind) b(); else if (kind === Kind.C) c();",
      errors: [{ messageId: "preferSwitch", data: { discriminant: "kind" } }],
    },
    {
      code: "if (kind === STATUS_A) a(); else if (STATUS_B === kind) b(); else if (kind === STATUS_C) c();",
      errors: [{ messageId: "preferSwitch", data: { discriminant: "kind" } }],
    },
  ],
});

void PREFER_SWITCH_FOR_REPEATED_EQUALITY_DOCUMENTATION;
