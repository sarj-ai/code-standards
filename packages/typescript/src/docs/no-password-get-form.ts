/** @fileoverview no-password-get-form — source-owned documentation and executable examples. */
import type { RuleDocumentation } from "../documentation.js";

export const NO_PASSWORD_GET_FORM_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Keep named password controls out of native GET form submissions.",
  rationale:
    "Native GET submission serializes enabled, named password controls into the URL, exposing credentials through browser history and request logs. GET is also the default for missing or invalid method attributes.",
  remediation:
    "Review the destination endpoint and submit credentials with POST. Keep server-side validation, HTTPS and the appropriate anti-CSRF protections; this rule only checks the native form serialization boundary.",
  category: "security",
  requiresTypeInformation: false,
  limitations: [
    "Only native form elements and direct intrinsic/fragment descendants are proved. Custom components, expressions, external form ownership, disabled fieldsets and unknown spreads are preserved.",
    "Forms with custom submission handlers, function or dynamic actions, or dynamic methods are left to review. React function actions submit using POST even when the method is omitted.",
    "Unnamed, empty-name and disabled password controls are not successful controls. The detector reports once per offending form and does not infer sensitive data from field names.",
  ],
  references: [
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/forms/forms.md",
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/forms/autofill-sign-in-form.md",
  ],
  examples: [
    {
      id: "post-password",
      title: "Submit the password with POST",
      outcome: "no-match",
      files: [
        {
          path: "src/view.tsx",
          source: '<form method="post"><input type="password" name="password" /></form>',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "default-get-password",
      title: "Review password serialization into the URL",
      outcome: "match",
      files: [
        {
          path: "src/view.tsx",
          source: '<form><input type="password" name="password" /></form>',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
