import * as parser from "@typescript-eslint/parser";
import { RuleTester } from "@typescript-eslint/rule-tester";
import { afterAll, describe, it } from "vitest";

import rule from "../../src/rules/no-unlocalized-toast.js";

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
