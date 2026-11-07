/** @fileoverview no-dangerously-allow-svg — the documentation and executable examples of `@sarj/no-dangerously-allow-svg`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DANGEROUSLY_ALLOW_SVG_DOCUMENTATION = {
  summary: "Require an explicit hardening policy for Next Image SVG delivery",
  rationale:
    "SVG can contain scripts and other active content. This organizational rule requires a recognized explicit script-blocking sandbox CSP when SVG delivery is enabled, with attachment disposition. It does not establish that framework defaults are missing or that a reported configuration is exploitable.",
  remediation:
    "Disable dangerouslyAllowSVG, or configure an explicit literal image contentSecurityPolicy such as `script-src 'none'; sandbox;` and keep attachment disposition. Verify effective headers and defaults against the application's pinned Next version.",
  category: "security",
  autofix: "safe",
  references: [
    "https://www.w3.org/TR/2026/WD-CSP3-20261027/#parse-serialized-policy",
    "https://github.com/vercel/next.js/blob/v16.4.3/packages/next/src/shared/lib/image-config.ts#L255",
  ],
  limitations: [
    "Automatic boolean changes are withheld when the module contains explicit TypeScript or JSDoc contracts; those contracts can constrain an aliased property to literal true. Plain objects and as const inference remain fixable.",
    "This rule does not resolve the installed Next version or evaluate effective response headers. The inspected Next 16.4.3 defaults already block scripts, apply sandbox, and use attachment disposition. A report for omitted explicit CSP is a policy finding, not proof of XSS.",
    "Omitted contentDispositionType is treated as attachment. Older or customized runtime defaults are not established by this source-only check.",
    "Only a bounded literal CSP subset is recognized: the first script-src must contain only 'none', and the first sandbox must have no tokens. Directive names and separators use CSP ASCII syntax. Valid policy lists, default-src fallbacks and other equivalent policies are not proved; omitted, dynamic or unrecognized explicit policies can still report. This is not a general CSP validator or proof of runtime security.",
    "Automatic fixes disable SVG opt-in to satisfy this policy; recognized hardened configurations are preserved. Only literal effective properties of a directly exported object, unescaped const alias, or isolated module.exports object are analyzed. Wrappers, factories, spreads, dynamic computed keys and mutations are not inferred.",
  ],
  examples: [
    {
      id: "svg-disabled",
      title: "Keep active SVG delivery disabled",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: false } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "svg-enabled",
      title: "SVG opt-in requires explicit hardening under this policy",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 1,
      public: true,
    },
    {
      id: "safe-autofix",
      title: "Disable SVG delivery to satisfy this policy",
      outcome: "match",
      files: [{ path: "next.config.ts", source: "export default { images: { dangerouslyAllowSVG: true } };" }],
      fixedFiles: [{ path: "next.config.ts", source: "export default { images: { dangerouslyAllowSVG: false } };" }],
      focusPath: "next.config.ts",
      expectedCount: 1,
    },
    {
      id: "svg-explicit-hardening",
      scenarioId: "explicit-hardening",
      title: "Allow SVG delivery with explicit hardening",
      outcome: "no-match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: \"attachment\", contentSecurityPolicy: \"script-src 'none'; sandbox;\" } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 0,
      public: true,
    },
    {
      id: "svg-unsafe-first-directive",
      scenarioId: "explicit-hardening",
      title: "A later duplicate cannot replace the effective policy",
      outcome: "match",
      files: [{ path: "next.config.mjs", source: "export default { images: { dangerouslyAllowSVG: true, contentDispositionType: \"attachment\", contentSecurityPolicy: \"script-src 'unsafe-inline'; script-src 'none'; sandbox;\" } };\n" }],
      focusPath: "next.config.mjs",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
