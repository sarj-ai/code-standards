/** @fileoverview no-unnecessary-use-client — the documentation and executable examples of `@sarj/no-unnecessary-use-client`. */

import type { RuleDocumentation } from "../documentation.js";

export const NO_UNNECESSARY_USE_CLIENT_DOCUMENTATION = {
  summary: "Flag `'use client'` files with no hooks or event handlers — they could be RSC.",
  rationale: "An unnecessary client boundary sends the component and its transitive dependencies to the browser without using client-only behavior.",
  remediation: "Review whether the directive can be removed after checking transitive client requirements and intended export boundaries; local syntax alone does not prove server compatibility.",
  category: "performance",
  limitations: ["Client need is inferred from recognized hooks, handlers, browser globals, exports, classes, and known client-only imports. Unknown side-effect imports preserve the boundary; arbitrary transitive runtime requirements are not inspected."],
  examples: [
    {
      id: "interactive-component",
      title: "Keep the directive for interactive components",
      outcome: "no-match",
      files: [{ path: "src/counter.tsx", source: "'use client'; import { useState } from 'react'; export default function X() { const [n] = useState(0); return <div>{n}</div>; }" }],
      focusPath: "src/counter.tsx",
      expectedCount: 0,
      public: true,
    },
    {
      id: "static-component",
      title: "Remove the directive from static components",
      outcome: "match",
      files: [{ path: "src/banner.tsx", source: "'use client'; export default function X() { return <div>hello</div>; }" }],
      focusPath: "src/banner.tsx",
      expectedCount: 1,
      public: true,
    },
  ],
} as const satisfies RuleDocumentation;
