/** @fileoverview no-blocked-input-paste — source-owned documentation and executable examples. */
import type { RuleDocumentation } from "../documentation.js";

export const NO_BLOCKED_INPUT_PASTE_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Allow clipboard input when a text control has no replacement paste handling.",
  rationale:
    "An editable text control that only cancels paste prevents users from entering generated passwords, authentication codes and copied data. This creates avoidable accessibility and password-manager barriers.",
  remediation:
    "Allow native paste. If the product must normalize clipboard content, provide explicit replacement processing and preserve keyboard and password-manager access; review the behavior instead of applying an automatic edit.",
  category: "correctness",
  requiresTypeInformation: false,
  limitations: [
    "An unresolved alternate paste phase or spread may supply replacement handling and suppresses the warning.",
    "Only intrinsic editable input and textarea handlers whose complete inline body is a direct preventDefault() call are reported.",
    "Clipboard processing, conditional cancellation, referenced handlers, rich editors, non-text inputs, custom components, optional calls and uncertain effective props remain outside the detector.",
  ],
  references: [
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/forms/forms.md",
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/forms/autofill-sign-in-form.md",
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/forms/sms-otp-form.md",
  ],
  examples: [
    {
      id: "native-paste",
      title: "Allow native clipboard input",
      outcome: "no-match",
      files: [
        {
          path: "src/view.tsx",
          source: '<input type="password" />',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "pure-paste-blocker",
      title: "Review unconditional paste cancellation",
      outcome: "match",
      files: [
        {
          path: "src/view.tsx",
          source: '<input type="password" onPaste={event => event.preventDefault()} />',
        },
      ],
      focusPath: "src/view.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
