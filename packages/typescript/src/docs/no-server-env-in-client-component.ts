/** @fileoverview no-server-env-in-client-component — the documentation and executable examples of `@sarj/no-server-env-in-client-component`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_SERVER_ENV_IN_CLIENT_COMPONENT_DOCUMENTATION = {
  summary: "server-only environment settings imported or re-exported by a client module",
  rationale:
    "Next.js client modules run in the browser, where server-only environment values are unavailable; importing or re-exporting a server settings module can produce undefined configuration or bundle a secret-bearing module into the client graph.",
  remediation:
    "Pass an explicitly public value from a Server Component, or import/re-export it from a separately validated client-settings module backed only by NEXT_PUBLIC_* values.",
  category: "correctness",
  limitations: [
    "Only direct static runtime imports and re-exports in files with a top-level 'use client' directive targeting the existing server-env/server-settings module protocol are checked. Type-only declarations/specifiers, local exports without a source and ordinary server modules are excluded.",
    "Dynamic imports, require calls and transitive barrel graphs are not followed. Public client-settings modules and unrelated module paths are not classified as server-only.",
  ],
  examples: [
    {
      id: "public-client-settings",
      title: "Import a browser-safe settings boundary",
      outcome: "no-match",
      files: [
        {
          path: "status-card.tsx",
          source:
            "'use client';\nimport { CLIENT_SETTINGS } from '@/client-settings';\nexport const StatusCard = () => <p>{CLIENT_SETTINGS.apiOrigin}</p>;\n",
        },
      ],
      focusPath: "status-card.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "server-settings-client-import",
      title: "Do not pull server settings into a client bundle",
      outcome: "match",
      files: [
        {
          path: "status-card.tsx",
          source:
            "'use client';\nimport { SERVER_SETTINGS } from '@/server-settings';\nexport const StatusCard = () => <p>{SERVER_SETTINGS.apiOrigin}</p>;\n",
        },
      ],
      focusPath: "status-card.tsx",
      expectedCount: 1,
      public: true,
    },
    {
      id: "public-client-settings-re-export",
      scenarioId: "client-re-export",
      title: "Forward public settings from the client boundary",
      outcome: "no-match",
      files: [
        {
          path: "client-barrel.tsx",
          source: "'use client';\nexport { CLIENT_SETTINGS } from './client-settings.js';\n",
        },
        {
          path: "client-settings.ts",
          source:
            "import { z } from 'zod';\nconst SettingsSchema = z.object({ apiOrigin: z.url() });\nexport const CLIENT_SETTINGS = SettingsSchema.parse({ apiOrigin: process.env.NEXT_PUBLIC_API_ORIGIN });\n",
        },
      ],
      focusPath: "client-barrel.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "server-settings-client-re-export",
      scenarioId: "client-re-export",
      title: "A client barrel cannot forward server settings",
      outcome: "match",
      files: [
        {
          path: "client-barrel.tsx",
          source: "'use client';\nexport { SERVER_SETTINGS } from './server-settings.js';\n",
        },
        {
          path: "server-settings.ts",
          source:
            "import { z } from 'zod';\nconst SettingsSchema = z.object({ apiOrigin: z.url() });\nexport const SERVER_SETTINGS = SettingsSchema.parse({ apiOrigin: process.env.API_ORIGIN });\n",
        },
      ],
      focusPath: "client-barrel.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
