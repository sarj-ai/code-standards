/** @fileoverview no-unlocalized-toast — the documentation and executable examples of `@sarj/no-unlocalized-toast`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNLOCALIZED_TOAST_DOCUMENTATION = {
  summary:
    "Require translation for literal toast messages in opted-in localized interfaces.",
  rationale:
    "User-facing notifications remain in a fixed language when their messages bypass translation.",
  remediation:
    "Pass the user-facing message through the configured translation API, or explicitly exempt text that must remain literal.",
  category: "correctness",
  limitations: [
    "Shared presets set enabled:false. Standalone rule activation opts into localization for the selected files. No particular locale or translation function name is required. Generated files, tests, fixtures and stories are excluded.",
    "Recognizes configured imported functions and their configured methods with message in argument zero. Defaults cover sonner toast and react-hot-toast default exports. Imports and shadows are scope-resolved. Promise/config-object notifications and dynamic messages are not analyzed.",
  ],
  examples: [
    {
      id: "literal-message",
      title: "Translate a user-facing message",
      outcome: "match",
      files: [
        {
          path: "src/message.tsx",
          source: 'import { toast } from "sonner"; toast.success("Saved");',
        },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "translated-message",
      title: "Resolve the message through translation",
      outcome: "no-match",
      files: [
        {
          path: "src/message.tsx",
          source: 'import { toast } from "sonner"; toast.success(t("saved"));',
        },
      ],
      focusPath: "src/message.tsx",
      expectedCount: 0,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
