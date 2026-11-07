/** @fileoverview no-client-side-data-fetching — the documentation and executable examples of `@sarj/no-client-side-data-fetching`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_CLIENT_SIDE_DATA_FETCHING_DOCUMENTATION = {
  summary: "Disallow direct data fetching inside `useEffect` or `useLayoutEffect`.",
  rationale:
    "Effect-driven reads begin after rendering and can create request waterfalls, duplicate fetches, and loading-state layout shifts.",
  remediation:
    "Fetch in a React Server Component or Server Action, or use a client cache such as SWR or React Query.",
  category: "performance",
  limitations: [
    "The rule recognizes common fetch clients syntactically and exempts analytics endpoints and non-GET `fetch` calls.",
  ],
  examples: [
    {
      id: "effect-without-fetch",
      title: "Load data while rendering on the server",
      outcome: "no-match",
      files: [
        { path: "app/users/page.tsx", source: "import { loadUsers } from './users-client';\nexport default async function Users() { const users = await loadUsers(); return <pre>{JSON.stringify(users)}</pre>; }" },
        { path: "app/users/users-client.ts", source: "export async function loadUsers(): Promise<unknown> { const response = await fetch('https://api.example.com/users'); return response.json(); }" },
      ],
      focusPath: "app/users/page.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "fetch-inside-effect",
      title: "An effect starts a data request",
      outcome: "match",
      files: [{ path: "src/users.tsx", source: "'use client'; import { useEffect } from 'react';\nexport function Users() { useEffect(() => { fetch('/api/users'); }, []); return null; }" }],
      focusPath: "src/users.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
