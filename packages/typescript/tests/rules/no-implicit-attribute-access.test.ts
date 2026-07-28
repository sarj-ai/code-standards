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
    { code: "const val = ctx.participant.attributes;" }, // just accessing attributes, not .get or []
    { code: "const val = process.env.get('FOO');" }, // Excluded base
    { code: "const val = headers['Authorization'];" }, // Excluded base
    { code: "const val = myDict.get(dynamicKey);" }, // Dynamic key is allowed
    { code: "const val = myDict[dynamicKey];" }, // Dynamic key is allowed
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
      code: "const val = myDict['foo'];",
      errors: [{ messageId: "noImplicitAttributeAccess" }],
    },
    {
      code: "const val = someRandomObj.get('price');",
      errors: [{ messageId: "noImplicitAttributeAccess" }],
    },
  ],
});
