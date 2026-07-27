import * as tsParser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/button-requires-type.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;

const ruleTester = new RuleTester({
  languageOptions: {
    parser: tsParser,
    parserOptions: {
      ecmaFeatures: { jsx: true },
    },
  },
});

ruleTester.run("button-requires-type", rule, {
  valid: [
    { code: '<button type="button">Open</button>' },
    { code: '<button type="submit">Save</button>' },
    { code: '<button type={kind}>Run</button>' },
    { code: '<Button onClick={save}>Save</Button>' },
    { code: '<buttonish onClick={save}>Save</buttonish>' },
    {
      code: "<button>Fixture markup</button>",
      filename: "/repo/src/__tests__/fixtures/edit-form.tsx",
    },
    {
      code: "<button>Story control</button>",
      filename: "/repo/src/button.stories.tsx",
    },
    {
      code: "// @generated\nexport const fixture = <button>Generated</button>;",
      filename: "/repo/src/generated/form.tsx",
    },
  ],
  invalid: [
    {
      code: "<button>Open</button>",
      errors: [{ messageId: "missingType" }],
    },
    {
      code: '<button className="link" onClick={openTemplates}>Templates</button>',
      errors: [{ messageId: "missingType" }],
    },
    {
      code: "<button {...props}>Submit</button>",
      errors: [{ messageId: "missingType" }],
    },
  ],
});
