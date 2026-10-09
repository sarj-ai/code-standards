// vitest: shared-module-graph
import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-unlocalized-toast.js";

import { verifyRuleExamples } from "../../src/verify-rule-examples.js";

RuleTester.afterAll = afterAll;
RuleTester.describe = describe;
RuleTester.it = it;
RuleTester.itOnly = it.only;
const RULE_TESTER = new RuleTester({
  languageOptions: { parser, parserOptions: { ecmaFeatures: { jsx: true } } },
  defaultFilenames: { ts: "/repo/src/action.ts", tsx: "/repo/src/action.tsx" },
});

RULE_TESTER.run("no-unlocalized-toast", rule, {
  valid: [
    'import { toast } from "sonner"; toast.success(t("saved"));',
    'const toast = { success() {} }; toast.success("saved");',
    'import { toast } from "sonner"; function show(toast) { toast.success("saved"); }',
    {
      code: 'import { toast } from "sonner"; toast.success("saved");',
      options: [{ enabled: false }],
    },
    'import { toast } from "sonner"; toast.dismiss("request-id");',
    'import { toast } from "sonner"; toast.promise(operation, { loading: "Loading" });',
  ],
  invalid: [
    {
      code: 'import { toast as notify } from "sonner"; notify.success("Saved");',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: 'import toast from "react-hot-toast"; toast("Saved");',
      errors: [{ messageId: "unlocalized" }],
    },
    {
      code: 'import { show } from "notifications"; show("Saved");',
      options: [{ functions: [{ module: "notifications", export: "show" }] }],
      errors: [{ messageId: "unlocalized" }],
    },
  ],
});


it("preserves outcomes for static member access and unknown member keys", async () => {
  const documentation = rule.documentation;
  if (documentation === undefined) throw new Error("Missing rule documentation");
  await verifyRuleExamples({ ...rule, documentation: { ...documentation, examples: [
  {
    "id": "literal-message-static-member",
    "title": "Static member access preserves the rule outcome",
    "outcome": "match",
    "focusPath": "src/message.tsx",
    "expectedCount": 1,
    "files": [
      {
        "path": "src/message.tsx",
        "source": "import { toast } from \"sonner\"; toast[\"success\"](\"Saved\");"
      }
    ]
  },
  {
    "id": "literal-message-dynamic-member",
    "title": "Unknown member access does not establish API identity",
    "outcome": "no-match",
    "focusPath": "src/message.tsx",
    "expectedCount": 0,
    "files": [
      {
        "path": "src/message.tsx",
        "source": "import { toast } from \"sonner\"; toast[auditDynamicMember](\"Saved\");"
      }
    ]
  }
] } });
});
