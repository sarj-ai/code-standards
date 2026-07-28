import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-implicit-attribute-access.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
  },
});

ruleTester.run("no-implicit-attribute-access", rule, {
  valid: [
    { code: "const val = attrs.sipPhoneNumber;" },
    { code: "const val = myDict.get('foo');" },
    { code: "const val = myDict['foo'];" },
    { code: "const val = ctx.participant.attributes;" }, // just accessing attributes, not .get or []
  ],
  invalid: [
    {
      code: "const val = ctx.participant.attributes.get('sip.phoneNumber');",
      errors: [{ messageId: "noImplicitAttributeAccess" }],
    },
    {
      code: "const val = event.payload.get('user_id');",
      errors: [{ messageId: "noImplicitAttributeAccess" }],
    },
    {
      code: "const val = event.meta['user_id'];",
      errors: [{ messageId: "noImplicitAttributeAccess" }],
    },
    {
      code: "const val = ctx.attributes['foo'];",
      errors: [{ messageId: "noImplicitAttributeAccess" }],
    },
  ],
});
