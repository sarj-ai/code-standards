/** @fileoverview no-secret-in-log — the documentation and executable examples of `@sarj/no-secret-in-log`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SECRET_IN_LOG_DOCUMENTATION = {
  summary: "Disallow passing a secret-named value or a raw request/response blob to a logging call; both leak to log sinks. Redact or omit.",
  rationale: "Logs are widely retained and distributed, so credentials and raw bodies can become durable data leaks.",
  remediation: "Omit the value, log allowlisted non-sensitive context, or use an approved redactor; truncation alone is not a safety guarantee.",
  category: "security",
  limitations: ["Detection uses configurable logger names and statically recognizable secret names, raw-body names, and redaction markers. Literal containers, template/string concatenation expressions, direct slice/substring/substr calls, and unshadowed global JSON.stringify without a replacer are inspected; unknown spreads, computed properties, aliases, replacers, and opaque calls are not followed. Name-based exemptions are policy heuristics, not proof that a value is safely redacted."],
  examples: [
    { id: "redacted-secret", title: "Log non-sensitive context instead of the secret", outcome: "no-match", files: [{ path: "src/auth.ts", source: "logger.info('auth', { requestId });" }], focusPath: "src/auth.ts", expectedCount: 0, public: true },
    { id: "logged-secret", title: "Do not send a secret to logs", outcome: "match", files: [{ path: "src/auth.ts", source: "logger.error('auth failed', { token });" }], focusPath: "src/auth.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
