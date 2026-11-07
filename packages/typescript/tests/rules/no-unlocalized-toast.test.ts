// vitest: shared-module-graph
import rule from "../../src/rules/no-unlocalized-toast.js";
import { ruleTester } from "./_tester.js";

const RULE_TESTER = ruleTester({ lang: "tsx" });

RULE_TESTER.run("no-unlocalized-toast", rule, {
  valid: [
    { name: "keeps explicit localization opt-out with an erased literal", code: 'import { toast } from "sonner"; toast.success(("Saved" as const));', options: [{ enabled: false }] },
    { name: "keeps translation through an erased wrapper", code: 'import { toast } from "sonner"; toast.success((t("saved") as string));' },
    { name: "keeps unknown computed methods opaque", code: 'import { toast } from "sonner"; toast[method](("Saved" as const));' },
    { name: "keeps shadowed computed toast methods outside the policy", code: 'import { toast } from "sonner"; function show(toast) { toast["success"](("Saved" as const)); }' },

    'import { toast } from "sonner"; toast.success(t("saved"));',
    'const toast = { success() {} }; toast.success("saved");',
    'import { toast } from "sonner"; function show(toast) { toast.success("saved"); }',
    {
      code: 'import { toast } from "sonner"; toast.success("saved");',
      options: [{ enabled: false }],
    },
    'import { toast } from "sonner"; toast.dismiss("request-id");',
    'import { toast } from "sonner"; toast.promise(operation, { loading: "Loading" });',
    {
      name: "literal-message-dynamic-member: Unknown member access does not establish API identity",
      filename: "src/message.tsx",
      code: 'import { toast } from "sonner"; toast[auditDynamicMember]("Saved");',
    },
  ],
  invalid: [
    { name: "retains a literal toast message through satisfies", code: 'import { toast } from "sonner"; toast.success(("Saved" satisfies string));', errors: [{ messageId: "unlocalized" }] },
    { name: "recognizes an imported static computed toast method", code: 'import { toast } from "sonner"; toast["success"](("Saved" as const));', errors: [{ messageId: "unlocalized" }] },

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
    {
      name: "literal-message-static-member: Static member access preserves the rule outcome",
      filename: "src/message.tsx",
      code: 'import { toast } from "sonner"; toast["success"]("Saved");',
      errors: [{ messageId: "unlocalized" }],
    },
  ],
});
