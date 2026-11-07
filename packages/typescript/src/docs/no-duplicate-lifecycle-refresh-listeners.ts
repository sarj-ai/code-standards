/** @fileoverview no-duplicate-lifecycle-refresh-listeners — the documentation and executable examples of `@sarj/no-duplicate-lifecycle-refresh-listeners`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_DUPLICATE_LIFECYCLE_REFRESH_LISTENERS_DOCUMENTATION = {
  summary: "Do not register one Next.js route-refresh callback for both focus and visibilitychange.",
  rationale: "A browser tab activation can emit both lifecycle signals and invoke the same route-wide refresh twice.",
  remediation: "Choose one lifecycle signal or route both signals through an explicitly debounced refresh policy.",
  category: "performance",
  limitations: ["Only active direct window focus and document visibilitychange statements in the same block whose shared identifier callback directly calls refresh on a next/navigation useRouter binding are inspected; matching direct removals are honored, and generated and test files are excluded."],
  examples: [
    { id: "single-lifecycle-signal", title: "Listen to one lifecycle signal", outcome: "no-match", files: [{ path: "src/refresh.ts", source: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener("focus", refresh);' }], focusPath: "src/refresh.ts", expectedCount: 0, public: true },
    { id: "duplicate-lifecycle-signals", title: "Do not duplicate a route refresh", outcome: "match", files: [{ path: "src/refresh.ts", source: 'import { useRouter } from "next/navigation"; const router = useRouter(); const refresh = () => router.refresh(); window.addEventListener("focus", refresh); document.addEventListener("visibilitychange", refresh);' }], focusPath: "src/refresh.ts", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
