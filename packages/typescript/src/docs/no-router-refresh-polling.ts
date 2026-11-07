/** @fileoverview no-router-refresh-polling — the documentation and executable examples of `@sarj/no-router-refresh-polling`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_ROUTER_REFRESH_POLLING_DOCUMENTATION = {
  summary: "Do not poll by calling a Next.js router's refresh method from a timer.",
  rationale: "A route refresh refetches and rerenders the whole route on every tick instead of loading the named resource that changed.",
  remediation: "Call the dedicated fetch or server action from the timer and keep the polling interval in a named constant.",
  category: "performance",
  limitations: ["Only router bindings created from next/navigation useRouter and direct setInterval or window.setInterval callbacks are inspected; generated and test files are excluded."],
  examples: [
    { id: "poll-named-action", title: "Poll a named resource", outcome: "no-match", files: [{ path: "src/status.tsx", source: '"use client"; import { useEffect } from "react"; function Status() { useEffect(() => { const timer = setInterval(() => fetchStatus(), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, []); return null; }' }], focusPath: "src/status.tsx", expectedCount: 0, public: true },
    { id: "poll-router-refresh", title: "Do not poll the whole route", outcome: "match", files: [{ path: "src/status.tsx", source: '"use client"; import { useEffect } from "react"; import { useRouter } from "next/navigation"; function Status() { const router = useRouter(); useEffect(() => { const timer = setInterval(() => router.refresh(), POLLING_INTERVAL_MS); return () => clearInterval(timer); }, [router]); return null; }' }], focusPath: "src/status.tsx", expectedCount: 1, public: true },
  ],
} as const satisfies RuleDocumentation;
