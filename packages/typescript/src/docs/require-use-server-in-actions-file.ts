/** @fileoverview require-use-server-in-actions-file — the documentation and executable examples of `@sarj/require-use-server-in-actions-file`. */

import type { RuleDocumentation } from "../documentation.js";

export const REQUIRE_USE_SERVER_IN_ACTIONS_FILE_DOCUMENTATION = {
  summary: "route action module missing the use server directive",
  rationale:
    "An exported async function is not callable as a Server Action merely because its file is named actions.ts. Without the module directive, a client import can fail or pull server-only implementation details across the client boundary.",
  remediation: "Use a leading module directive for an action-only module, or retain a function-level directive for an inline Server Action. Do not turn mixed non-action exports into a Server Action module.",
  category: "correctness",
  limitations: [
    "Only direct named exports of async declarations or initialized functions in actions.ts or *-actions.ts below an app directory are checked. Detached/default exports and other naming schemes are not inferred; functions with their own directive are accepted.",
  ],
  examples: [
    {
      id: "server-action-module",
      title: "Mark the action module as server-only",
      outcome: "no-match",
      files: [{ path: "app/orders/actions.ts", source: "'use server';\nexport async function cancelOrder() {}\n" }],
      focusPath: "app/orders/actions.ts",
      expectedCount: 0,
      public: true,
    },
    {
      id: "unmarked-action-module",
      title: "Do not rely on the filename to create a Server Action",
      outcome: "match",
      files: [{ path: "app/orders/actions.ts", source: "export async function cancelOrder() {}\n" }],
      focusPath: "app/orders/actions.ts",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
