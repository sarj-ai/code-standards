/** @fileoverview prefer-server-actions — the documentation and executable examples of `@sarj/prefer-server-actions`. */

import type { RuleDocumentation } from "../documentation.js";

export const PREFER_SERVER_ACTIONS_DOCUMENTATION = {
  summary: "Prefer Next.js Server Actions over same-origin API mutations.",
  rationale: "Server Actions can remove a hand-written internal API wrapper while retaining typed application calls. Client invocations still cross a network and serialization boundary.",
  remediation: "Consider a Server Action for application-owned mutations; preserve authorization, input validation and any public API consumers.",
  category: "architecture",
  limitations: ["Only statically recognizable /api/ mutations through global fetch or proven Axios imports/instances in use-client modules are reported. Custom wrapper provenance, mutated configuration and unknown option overrides are not inferred; server boundaries and route handlers are excluded."],
  examples: [
    { id: "server-action-call", title: "Call a Server Action", outcome: "no-match", files: [{ path: "app/tasks/page.tsx", source: "import { createTask } from './actions'; await createTask(input);" }], focusPath: "app/tasks/page.tsx", expectedCount: 0, public: true },
    { id: "api-mutation", title: "Do not mutate through an API route", outcome: "match", files: [{ path: "app/tasks/page.tsx", source: "'use client'; await fetch('/api/tasks', { method: 'POST', body });" }], focusPath: "app/tasks/page.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
