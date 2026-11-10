/** @fileoverview no-message-origin-string-matching — source-owned documentation and executable examples. */
import type { RuleDocumentation } from "../documentation.js";

export const NO_MESSAGE_ORIGIN_STRING_MATCHING_DOCUMENTATION = {
  defaultLevel: "warning",
  summary: "Compare incoming browser message origins against exact trusted origins.",
  rationale:
    "Prefix, suffix and substring checks do not establish an origin trust boundary. For example, https://trusted.example.attacker.invalid passes a prefix check against https://trusted.example.",
  remediation:
    "Compare exact allowlisted origins or parse the origin and validate the intended scheme, host and port. Reject opaque null origins unless a separately verified source/capability contract establishes trust; do not require an experimental Origin API.",
  category: "security",
  requiresTypeInformation: false,
  limitations: [
    "Only inline callbacks registered for message on ambient addEventListener, window, self or globalThis are tracked by variable identity.",
    "Named listeners, event aliases, transformed origin strings, regular expressions and cross-file authorization helpers are not followed. Ordinary object.origin strings and shadowed globals are preserved.",
    "This detects imprecise incoming origin matching, not all missing authorization checks. Outgoing target origins remain owned by Unicorn's require-post-message-target-origin rule.",
  ],
  references: [
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/security/validate-origins.md",
    "https://github.com/GoogleChrome/modern-web-guidance/blob/4dd968349e54ca45a05dd5c818fb035c9054b022/skills/modern-web-guidance/guides/security/security.md",
  ],
  examples: [
    {
      id: "exact-origin",
      title: "Compare an explicit trusted origin",
      outcome: "no-match",
      files: [
        {
          path: "src/listener.ts",
          source:
            'window.addEventListener("message", event => { if (event.origin === "https://trusted.example") accept(event.data); });',
        },
      ],
      focusPath: "src/listener.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "prefix-origin",
      title: "Review a spoofable origin prefix",
      outcome: "match",
      files: [
        {
          path: "src/listener.ts",
          source:
            'window.addEventListener("message", event => { if (event.origin.startsWith("https://trusted.example")) accept(event.data); });',
        },
      ],
      focusPath: "src/listener.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
